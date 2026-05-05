import asyncio
import json
import logging
import os
import random
import re
from typing import Any, Optional

import asyncpg
import numpy as np
from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pgvector.asyncpg import register_vector
from typing_extensions import TypedDict


# ── Graph State ───────────────────────────────────────────────────────────────

class ReWOOState(TypedDict):
    """State threaded through the three ReWOO nodes."""
    question: str
    question_history: list[str] # recent prior user inputs for follow-up context
    plan:     list[dict]        # [{id, tool, args}, …]  populated by planner
    evidence: dict[str, Any]    # {step_id: tool_result} populated by worker
    answer:   str               # final student-facing answer from solver


# ── Agent ─────────────────────────────────────────────────────────────────────

class CourseAdvisor:
    """
    ReWOO-style agentic academic advisor grounded in course syllabus documents.

    Architecture
    ────────────
    Planner → Worker → Solver

    • Planner  – one LLM call; emits a full JSON retrieval plan (#E1, #E2, …)
    • Worker   – executes all tool calls; dependency-free steps run concurrently
                 via asyncio.gather; dependent steps substitute placeholders first
    • Solver   – one LLM call; synthesises evidence into the student-facing answer
    """

    # ── Prompts ───────────────────────────────────────────────────────────────

    SYSTEM_PROMPT = """\
You are a helpful academic advisor for students at San José State University.
You have been given excerpts from official course syllabus documents.

Each excerpt begins with a header in this format:
    [SUBJECT CATALOG_NUMBER: Course Title | Instructor: Name |
     TERM YEAR Section XX | Delivery: mode | Units: N |
     Syllabus: <url>]
followed by a section heading (e.g. ## Grading Policy) and the excerpt text.

Rules:
- Answer ONLY using information explicitly stated in the syllabus excerpts provided.
- Do NOT use any outside knowledge, assumptions, or inferences beyond what the
  excerpts say. If the excerpts do not contain enough information to answer the
  question, say so clearly and do not guess.
- If information varies across sections (e.g. different instructors or semesters),
  acknowledge the differences rather than generalizing.
- If the prompt includes recent user questions, use them only to resolve references
  in the current question. Answer only the current question.
- Every claim you make must be traceable to a specific excerpt. At the end of your
  answer, list all syllabus URLs that contributed to your response as plain text
  on separate lines — do not hyperlink them, do not embed them in anchor text,
  just print the raw URL exactly as it appears in the excerpt header.
- Be concise, friendly, and clear.
"""

    PLANNER_SYSTEM_PROMPT = """\
You are a planning agent for an academic course advisor system at San José State University.

Given a student question, produce a step-by-step retrieval plan using the
retrieve_syllabus_chunks tool. The user message may include recent prior user
questions; use those only to resolve follow-up references such as "that course",
"the professor", "its exams", or "what about grading". Output ONLY a valid JSON object — no markdown
fences, no explanation, no preamble — with exactly this structure:

{
  "steps": [
    {
      "id": "#E1",
      "tool": "retrieve_syllabus_chunks",
      "args": {
        "query": "<semantic search query, e.g. 'course assignments', NOT a question>",
        "subject": "<optional subject code, e.g. CS, MATH>",
        "catalog_number": "<optional catalog number, e.g. 146, 101W>",
        "instructor": "<optional partial instructor name>",
        "section": "<optional section identifier>",
        "delivery": "<optional delivery mode, e.g. In Person, Online>",
        "year": <optional integer year, omit key entirely if unknown>,
        "session": "<optional session, e.g. Spring, Fall>"
      }
    }
  ]
}

Rules:
- Include only optional filter keys whose values you are confident about from
  the current question or recent prior user questions.  Omit keys you do not know
  — do not include them with null values.
- Use recent prior user questions only for context, not as extra questions to answer.
- A later step's "query" value may contain a prior step id as a placeholder
  (e.g. "#E1") if that step's retrieved content should inform the follow-up query.
  The worker will substitute the placeholder before executing the step.
- Produce ONE step per distinct information need in the question.  If the
  student asks about three separate topics (e.g. course content, grading, and
  projects), emit three steps with one focused query each.  Never merge multiple
  information needs into a single query; a combined query dilutes recall for
  every topic it covers.
- Output ONLY the JSON object, with absolutely no other text.
"""

    # ── Constants ─────────────────────────────────────────────────────────────

    EMBEDDING_MODEL  = "gemini-embedding-001"
    GENERATION_MODEL = "gemini-3-flash-preview"
    PLANNER_MODEL    = "gemini-3-flash-preview"   # same value; swap independently
    TOP_K            = 3

    _POOL_MIN_CONN      = 2
    _POOL_MAX_CONN      = 10
    _RETRY_MAX_ATTEMPTS = 4
    _RETRY_BASE_DELAY   = 1.0    # seconds
    _RETRY_MAX_DELAY    = 30.0   # seconds

    _HISTORY_MAX_QUESTIONS = 5
    _HISTORY_MAX_CHARS     = 1200

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._api_key = self._resolve_api_key()
        # genai.Client exposes async methods via the .aio property.
        # A single client is safe to share across coroutines.
        self._client = genai.Client(api_key=self._api_key)
        self._pool:  asyncpg.Pool | None = None
        self._graph = None   # compiled LangGraph; set in setup()

    async def setup(self) -> None:
        """
        Async initialisation — call once at startup before serving requests.

        Creates the asyncpg pool (registering the pgvector codec on every new
        connection), defines the @tool as a closure over self, builds the three
        ReWOO nodes, assembles the StateGraph, and compiles it.
        """
        self._pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "course_advisor"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            min_size=self._POOL_MIN_CONN,
            max_size=self._POOL_MAX_CONN,
            init=register_vector,   # registers pgvector codec on every connection
        )

        # ── @tool (closure gives the function access to pool + client) ────────
        _self = self

        @tool
        async def retrieve_syllabus_chunks(
            query:          str,
            subject:        Optional[str] = None,
            catalog_number: Optional[str] = None,
            instructor:     Optional[str] = None,
            section:        Optional[str] = None,
            delivery:       Optional[str] = None,
            year:           Optional[int] = None,
            session:        Optional[str] = None,
        ) -> list[dict]:
            """
            Retrieve the most semantically relevant syllabus chunks.

            Optionally narrow results by subject, catalog number, instructor,
            section, delivery mode, year, or session before ranking by vector
            similarity.  Similarity scores are never included in the output.
            """
            chunks = await _self._retrieve(
                query,
                subject=subject,
                catalog_number=catalog_number,
                instructor=instructor,
                section=section,
                delivery=delivery,
                year=year,
                session=session,
            )
            # Strip similarity — must never leak into the agent or the answer.
            return [{k: v for k, v in c.items() if k != "similarity"} for c in chunks]

        # ── LLM instances ─────────────────────────────────────────────────────
        # Gemini 3+ models require temperature=1.0; lower values cause infinite
        # loops and degraded performance.  Use thinking_level to control
        # reasoning depth instead of temperature.
        planner_llm = ChatGoogleGenerativeAI(
            model=self.PLANNER_MODEL,
            google_api_key=self._api_key,
            temperature=1.0,
            thinking_level="low",    # JSON templating needs no deep reasoning
        )
        solver_llm = ChatGoogleGenerativeAI(
            model=self.GENERATION_MODEL,
            google_api_key=self._api_key,
            temperature=1.0,
            thinking_level="medium", # some reasoning useful for multi-chunk synthesis
        )

        # ── Helper: extract text from LangChain response ──────────────────────

        def _extract_text(content) -> str:
            """
            Normalize a LangChain response content value to a plain string.

            When thinking_level is set, Gemini returns a list of typed blocks
            (e.g. {"type": "thinking", ...}, {"type": "text", "text": "..."}).
            When thinking is disabled the value is already a plain string.
            This helper handles both cases so callers can always do .strip().
            """
            if isinstance(content, str):
                return content
            # content is a list of dicts — concatenate all "text" blocks.
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )

        # ── Node: planner ─────────────────────────────────────────────────────

        async def planner_node(state: ReWOOState) -> dict:
            """
            Single LLM call.  Receives the student question; emits a full
            retrieval plan as a list of {id, tool, args} dicts.
            """
            planner_question = self._format_question_with_history(
                state["question"],
                state.get("question_history", []),
            )
            messages = [
                SystemMessage(content=self.PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=planner_question),
            ]
            response = await planner_llm.ainvoke(messages)
            raw = _extract_text(response.content).strip()
            # Defensively strip accidental markdown fences the model may emit.
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```\s*$",        "", raw)
            plan_data = json.loads(raw)
            return {"plan": plan_data["steps"]}

        # ── Node: worker ──────────────────────────────────────────────────────

        async def worker_node(state: ReWOOState) -> dict:
            """
            Executes every planned tool call.

            Steps with no placeholder dependencies on each other are dispatched
            concurrently via asyncio.gather.  Steps that reference a prior step's
            output (#E1, #E2, …) are executed only after that output is available,
            with the placeholder substituted into the args first.
            """
            plan    = state["plan"]
            evidence: dict[str, Any] = {}
            pending = list(plan)

            def _has_unresolved(args: dict) -> bool:
                """True if any arg value contains a #E placeholder not yet in evidence."""
                for v in args.values():
                    if isinstance(v, str):
                        for ref in re.findall(r"#E\d+", v):
                            if ref not in evidence:
                                return True
                return False

            def _resolve_args(args: dict) -> dict:
                """Substitute all known #E placeholders with their evidence values."""
                resolved = {}
                for k, v in args.items():
                    if isinstance(v, str):
                        for ref in re.findall(r"#E\d+", v):
                            if ref in evidence:
                                # Embed the JSON-serialised result so it is
                                # readable as a query string.
                                v = v.replace(ref, json.dumps(evidence[ref]))
                    resolved[k] = v
                return resolved

            async def _execute_step(step: dict) -> tuple[str, Any]:
                resolved = _resolve_args(step["args"])
                result   = await retrieve_syllabus_chunks.ainvoke(resolved)
                return step["id"], result

            while pending:
                # Gather all steps whose dependencies are already satisfied.
                ready = [s for s in pending if not _has_unresolved(s["args"])]
                if not ready:
                    # Guard against circular / malformed plan — skip remaining.
                    skipped = [s["id"] for s in pending]
                    logging.warning(
                        "worker_node: unresolvable placeholder dependencies; "
                        "skipping steps %s.  Solver will have incomplete evidence.",
                        skipped,
                    )
                    break

                # Dispatch all ready steps concurrently.
                results = await asyncio.gather(*[_execute_step(s) for s in ready])

                for step_id, result in results:
                    evidence[step_id] = result

                ready_ids = {s["id"] for s in ready}
                pending   = [s for s in pending if s["id"] not in ready_ids]

            return {"evidence": evidence}

        # ── Node: solver ──────────────────────────────────────────────────────

        async def solver_node(state: ReWOOState) -> dict:
            """
            Single LLM call.  Receives the original question plus all labeled
            evidence; produces the student-facing answer governed by SYSTEM_PROMPT.
            """
            # Merge chunks from all evidence steps (preserve insertion order).
            all_chunks: list[dict] = []
            for step_id in sorted(state["evidence"].keys()):
                step_chunks = state["evidence"][step_id]
                if isinstance(step_chunks, list):
                    all_chunks.extend(step_chunks)

            # Deduplicate by chunk_id so the same passage isn't repeated.
            seen: set[int] = set()
            unique_chunks: list[dict] = []
            for c in all_chunks:
                cid = c.get("chunk_id")
                if cid not in seen:
                    seen.add(cid)
                    unique_chunks.append(c)

            if not unique_chunks:
                return {
                    "answer": (
                        "I wasn't able to find any relevant syllabus content "
                        "to answer your question.  Please try rephrasing or "
                        "check that the course exists in the system."
                    )
                }

            context = self._format_context(unique_chunks)
            history = state.get("question_history", [])
            if history:
                history_text = "\n".join(
                    f"{i}. {item}" for i, item in enumerate(history, start=1)
                )
                user_prompt = (
                    f"The following are relevant syllabus excerpts retrieved for your question.\n\n"
                    f"{context}\n\n"
                    f"Recent user questions, oldest to newest. Use only to resolve "
                    f"references in the current question; do not answer these prior "
                    f"questions again.\n{history_text}\n\n"
                    f"Current student question: {state['question']}"
                )
            else:
                user_prompt = (
                    f"The following are relevant syllabus excerpts retrieved for your question.\n\n"
                    f"{context}\n\n"
                    f"Student question: {state['question']}"
                )
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
            response = await solver_llm.ainvoke(messages)
            return {"answer": _extract_text(response.content).strip()}

        # ── Graph assembly ────────────────────────────────────────────────────
        graph = StateGraph(ReWOOState)
        graph.add_node("planner", planner_node)
        graph.add_node("worker",  worker_node)
        graph.add_node("solver",  solver_node)
        graph.add_edge(START,      "planner")
        graph.add_edge("planner",  "worker")
        graph.add_edge("worker",   "solver")
        graph.add_edge("solver",   END)
        self._graph = graph.compile()

    async def close(self) -> None:
        """Release all pooled connections.  Call on application shutdown."""
        if self._pool:
            await self._pool.close()

    # ── Public interface ──────────────────────────────────────────────────────

    async def ask(
        self,
        question: str,
        history: Optional[list[str]] = None,
        verbose: bool = False,
    ) -> str:
        """
        Run the full ReWOO pipeline for a student question.

        Course identification (subject, catalog number, etc.) is now entirely
        the agent's responsibility — the caller passes only the raw question.

        history contains recent prior user questions from the same session. It is
        used only to resolve follow-up references; assistant answers are not
        stored or passed back into the advisor.

        Set verbose=True to print each node's output as it completes:
          • Planner  — the full retrieval plan (steps + args)
          • Worker   — every retrieved chunk per evidence key
          • Solver   — the final answer
        """
        # Backward compatibility for callers that used ask(question, verbose).
        if isinstance(history, bool) and verbose is False:
            verbose = history
            history = None

        initial_state = {
            "question": question,
            "question_history": self._recent_history(history),
            "plan":     [],
            "evidence": {},
            "answer":   "",
        }

        if not verbose:
            result = await self._graph.ainvoke(initial_state)
            return result["answer"]

        # ── Verbose: astream_events gives per-LLM-call granularity ──────────────
        # Event types we handle:
        #   on_chain_start        — a LangGraph node is beginning
        #   on_chat_model_start   — an LLM call is about to be made (shows prompt)
        #   on_chat_model_end     — an LLM call finished (shows raw response)
        #   on_chain_end          — a node finished (shows its state delta)

        _WIDE    = "━" * 60
        _DIVIDER = "─" * 60

        def _fmt_messages(messages: list) -> None:
            """Pretty-print a list of LangChain message dicts or objects."""
            for msg in messages:
                if isinstance(msg, dict):
                    role    = msg.get("type", msg.get("role", "?")).upper()
                    content = msg.get("text", msg.get("content", ""))
                elif hasattr(msg, "type") and hasattr(msg, "content"):
                    role    = msg.type.upper()
                    content = msg.content
                else:
                    role, content = "MSG", str(msg)

                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )

                indented = str(content).replace("\n", "\n    ")
                print(f"  [{role}]\n    {indented}\n")

        def _fmt_chunks(evidence: dict) -> None:
            """Print retrieved chunks from a worker state delta."""
            for eid, chunks in sorted(evidence.items()):
                if not isinstance(chunks, list):
                    continue
                print(f"\n  {eid}  →  {len(chunks)} chunk{'s' if len(chunks) != 1 else ''} retrieved")
                print(_DIVIDER)
                for i, c in enumerate(chunks, 1):
                    print(
                        f"  [{i}] {c.get('subject','?')}) {c.get('catalog_number','?')}"
                        f" — {c.get('chunk_title','(no title)')}"
                        f"  |  {c.get('session','?')}) {c.get('year','?')}"
                        f"  |  {c.get('instructor','?')}"
                    )
                    text    = c.get("chunk_text", "")
                    preview = text[:400].replace("\n", "\n       ")
                    if len(text) > 400:
                        preview += f"  … [{len(text) - 400} more chars]"
                    print(f"       {preview}\n")

        _NODE_LABELS = {"planner": "PLANNER", "worker": "WORKER", "solver": "SOLVER"}
        final_answer = ""

        async for event in self._graph.astream_events(initial_state, version="v2"):
            kind = event["event"]
            name = event.get("name", "")
            data = event.get("data", {})

            # ── Node starting ─────────────────────────────────────────────────
            if kind == "on_chain_start" and name in _NODE_LABELS:
                print(f"\n{_WIDE}")
                print(f"  ▶ {_NODE_LABELS[name]} starting")
                print(_WIDE)

            # ── LLM call: prompt ──────────────────────────────────────────────
            elif kind == "on_chat_model_start":
                batches  = data.get("input", {}).get("messages", [[]])
                messages = batches[0] if batches else []
                print(f"\n  ┌─ LLM CALL  ({name})  —  {len(messages)} message(s)")
                print(f"  └{'─' * 50}")
                _fmt_messages(messages)

            # ── LLM call: response ────────────────────────────────────────────
            elif kind == "on_chat_model_end":
                raw = data.get("output", {})
                try:
                    content = raw.generations[0][0].message.content
                except (AttributeError, IndexError):
                    content = str(raw)
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                preview = str(content)[:600].replace("\n", "\n    ")
                if len(str(content)) > 600:
                    preview += f"  … [{len(str(content)) - 600} more chars]"
                print(f"  ┌─ LLM RESPONSE  ({name})")
                print(f"  └{'─' * 50}")
                print(f"    {preview}\n")

            # ── Node finished ─────────────────────────────────────────────────
            elif kind == "on_chain_end" and name in _NODE_LABELS:
                output = data.get("output", {})
                if name == "planner":
                    plan = output.get("plan", [])
                    print(f"\n  ✔ PLANNER  →  {len(plan)} step(s)")
                    for step in plan:
                        print(f"    {step['id']}  tool={step['tool']}")
                        for k, v in step.get("args", {}).items():
                            print(f"         {k}: {v!r}")
                    print(_DIVIDER)
                elif name == "worker":
                    evidence = output.get("evidence", {})
                    print(f"\n  ✔ WORKER  →  {len(evidence)} evidence key(s)")
                    _fmt_chunks(evidence)
                    print(_DIVIDER)
                elif name == "solver":
                    final_answer = output.get("answer", "")
                    print(f"\n  ✔ SOLVER answer:")
                    print(_DIVIDER)
                    print(final_answer)
                    print(_WIDE)

        return final_answer

    # ── Retry ─────────────────────────────────────────────────────────────────

    async def _with_retry(self, fn, *args, **kwargs):
        """
        Call an async function with exponential backoff + full jitter.

        Retries only on transient errors (rate limits, server errors, network
        timeouts).  Non-transient errors (bad API key, invalid arguments, etc.)
        are re-raised immediately so the caller sees the real error without
        burning through retry budget.

        Full jitter (random * capped_delay) avoids thundering-herd re-bursts
        when many concurrent requests hit a rate limit at the same time.
        """
        from google.genai import errors as _genai_errors
        _TRANSIENT_STATUS = {429, 500, 502, 503, 504}
        for attempt in range(self._RETRY_MAX_ATTEMPTS):
            try:
                return await fn(*args, **kwargs)
            except _genai_errors.APIError as exc:
                if exc.code not in _TRANSIENT_STATUS or attempt == self._RETRY_MAX_ATTEMPTS - 1:
                    raise
            except (TimeoutError, ConnectionError, OSError):
                if attempt == self._RETRY_MAX_ATTEMPTS - 1:
                    raise
            cap   = min(self._RETRY_BASE_DELAY * (2 ** attempt), self._RETRY_MAX_DELAY)
            delay = random.uniform(0, cap)
            await asyncio.sleep(delay)

    # ── RAG ───────────────────────────────────────────────────────────────────

    async def _embed_query(self, text: str) -> np.ndarray:
        result = await self._with_retry(
            self._client.aio.models.embed_content,
            model=self.EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        return self._normalize(result.embeddings[0].values)

    @staticmethod
    def _normalize(values: list[float]) -> np.ndarray:
        """
        L2-normalise a vector using numpy.

        gemini-embedding-001 outputs 3072-dim vectors by default, which are
        pre-normalised.  Any reduced dimensionality (768, 1536, …) is NOT
        normalised by the API, so normalisation is required here before
        cosine-similarity search, otherwise dot-product results are wrong.
        """
        v    = np.array(values)
        norm = np.linalg.norm(v)
        return (v / norm) if norm > 0 else v

    async def _retrieve(
        self,
        question:       str,
        subject:        Optional[str] = None,
        catalog_number: Optional[str] = None,
        instructor:     Optional[str] = None,
        section:        Optional[str] = None,
        delivery:       Optional[str] = None,
        year:           Optional[int] = None,
        session:        Optional[str] = None,
    ) -> list[dict]:
        """
        Embed the question, then fetch the top-K most similar syllabus chunks.

        Filters are applied in a CTE that returns only chunk IDs. The outer query
        joins back to the physical syllabus_chunk table and performs the vector
        ORDER BY there, which lets pgvector use the HNSW index instead of ranking
        over a materialized derived table.

        The connection is held only for the query and returned before any LLM work.
        """
        embedding = await self._embed_query(question)

        conditions: list[str] = []
        params: list[Any] = [embedding]  # $1
        p = 2

        if subject:
            conditions.append(f"c.subject = ${p}")
            params.append(subject)
            p += 1

        if catalog_number:
            conditions.append(f"c.catalog_number = ${p}")
            params.append(catalog_number)
            p += 1

        if instructor:
            conditions.append(f"i.instructor_name ILIKE ${p}")
            params.append(f"%{instructor}%")
            p += 1

        if section:
            conditions.append(f"s.section = ${p}")
            params.append(section)
            p += 1

        if delivery:
            conditions.append(f"s.delivery = ${p}")
            params.append(delivery)
            p += 1

        if year is not None:
            conditions.append(f"s.year = ${p}")
            params.append(year)
            p += 1

        if session:
            conditions.append(f"s.session = ${p}")
            params.append(session)
            p += 1

        limit_param = f"${p}"
        params.append(self.TOP_K)

        select_cols = """
            sc.chunk_id,
            sc.chunk_title,
            sc.chunk_text,
            c.subject,
            c.catalog_number,
            s.course_title,
            s.units,
            s.session,
            s.year,
            s.section,
            s.delivery,
            s.syllabus_url,
            i.instructor_name,
            1 - (sc.embedding <=> $1) AS similarity
        """

        # No filters: keep the query as a pure vector search so HNSW can drive
        # the ORDER BY directly.
        if not conditions:
            sql = f"""
                SELECT
                    {select_cols}
                FROM syllabus_chunk sc
                JOIN section    s ON s.section_id     = sc.section_id
                JOIN course     c ON c.course_id      = s.course_id
                JOIN instructor i ON i.instructor_id  = s.instructor_id
                ORDER BY sc.embedding <=> $1
                LIMIT {limit_param};
            """
        else:
            where_clause = "WHERE " + " AND ".join(conditions)

            sql = f"""
                WITH filtered_ids AS (
                    SELECT sc.chunk_id
                    FROM syllabus_chunk sc
                    JOIN section    s ON s.section_id     = sc.section_id
                    JOIN course     c ON c.course_id      = s.course_id
                    JOIN instructor i ON i.instructor_id  = s.instructor_id
                    {where_clause}
                )
                SELECT
                    {select_cols}
                FROM syllabus_chunk sc
                JOIN filtered_ids fi ON fi.chunk_id       = sc.chunk_id
                JOIN section      s  ON s.section_id      = sc.section_id
                JOIN course       c  ON c.course_id       = s.course_id
                JOIN instructor   i  ON i.instructor_id   = s.instructor_id
                ORDER BY sc.embedding <=> $1
                LIMIT {limit_param};
            """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            {
                "chunk_id":       row["chunk_id"],
                "chunk_title":    row["chunk_title"],
                "chunk_text":     row["chunk_text"],
                "subject":        row["subject"],
                "catalog_number": row["catalog_number"],
                "course_title":   row["course_title"],
                "units":          row["units"],
                "session":        row["session"],
                "year":           row["year"],
                "section":        row["section"],
                "delivery":       row["delivery"],
                "syllabus_url":   row["syllabus_url"],
                "instructor":     row["instructor_name"],
                "similarity":     row["similarity"],
            }
            for row in rows
        ]

    def _format_context(self, chunks: list[dict]) -> str:
        """
        Format retrieved chunks as labelled excerpts for the solver.

        The Relevance / similarity field is intentionally omitted — it must
        never appear in the context passed to the solver or in the final answer.
        """
        return "\n\n---\n\n".join(
            (
                f"[{c['subject']} {c['catalog_number']}: {c['course_title']} | "
                f"Instructor: {c['instructor']} | "
                f"{c['session']} {c['year']} Section {c['section']} | "
                f"Delivery: {c['delivery']} | "
                f"Units: {c['units']} | "
                f"Syllabus: {c['syllabus_url']}]\n"
                f"## {c['chunk_title']}\n"
                f"{c['chunk_text']}"
            )
            for c in chunks
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _recent_history(self, history: Optional[list[str]]) -> list[str]:
        """Return a bounded, cleaned list of recent prior user inputs."""
        if not history:
            return []

        cleaned = [
            item.strip()
            for item in history
            if isinstance(item, str) and item.strip()
        ]
        recent = cleaned[-self._HISTORY_MAX_QUESTIONS:]

        kept_reversed: list[str] = []
        total_chars = 0
        for item in reversed(recent):
            next_total = total_chars + len(item)
            if kept_reversed and next_total > self._HISTORY_MAX_CHARS:
                break
            kept_reversed.append(item)
            total_chars = next_total

        return list(reversed(kept_reversed))

    def _format_question_with_history(
        self,
        question: str,
        history: Optional[list[str]],
    ) -> str:
        """Format the current question with prior user inputs for planning."""
        recent = self._recent_history(history)
        if not recent:
            return question

        history_text = "\n".join(
            f"{i}. {item}" for i, item in enumerate(recent, start=1)
        )
        return (
            "Recent user questions, oldest to newest. Use them only to resolve "
            "course, instructor, section, term, or delivery references in the "
            "current question. Do not answer the prior questions again.\n"
            f"{history_text}\n\n"
            f"Current student question:\n{question}"
        )

    @staticmethod
    def _resolve_api_key() -> str:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError(
                "Missing API key.  Set GOOGLE_API_KEY in your environment."
            )
        return key
