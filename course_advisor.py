import asyncio
import os
import random

import asyncpg
import numpy as np
from google import genai
from google.genai import types
from pgvector.asyncpg import register_vector


class CourseAdvisor:
    """An AI-powered academic advisor grounded in course syllabus documents via RAG."""

    SYSTEM_PROMPT = """\
    You are a helpful academic advisor for students at San José State University.
    You have been given the most relevant excerpts from official course syllabus
    documents across one or more sections of the requested course.

    Each excerpt begins with a header in this format:
        [SUBJECT CATALOG_NUMBER: Course Title | Instructor: Name |
         TERM YEAR Section XX | Delivery: mode | Units: N |
         Syllabus: <url> | Relevance: 0.00]
    followed by a section heading (e.g. ## Grading Policy) and the excerpt text.

    Rules:
    - Base your answer only on the syllabus excerpts provided.
    - Use the section heading (e.g. ## Grading Policy) to locate and cite which
      part of the syllabus your answer comes from.
    - If information varies across sections (e.g. different instructors or
      semesters), acknowledge the differences rather than generalizing.
    - If an excerpt has a Relevance score below 0.70, treat it as a weak match.
      Use it only if no stronger excerpts address the question, and note the
      uncertainty in your answer.
    - When it would help the student verify details, include the Syllabus URL
      so they can check the source directly.
    - If the excerpts don't cover the question, say so honestly.
    - Be concise, friendly, and clear.
    """

    EMBEDDING_MODEL  = "gemini-embedding-001"
    GENERATION_MODEL = "gemini-3-flash-preview"
    TOP_K            = 5

    # DB pool — tune to your Postgres max_connections budget.
    # No longer tied to thread count: connections are only held for the
    # brief vector search, not for the full duration of the LLM calls.
    _POOL_MIN_CONN = 2
    _POOL_MAX_CONN = 10

    # Retry config for Gemini API calls.
    # Exponential backoff with full jitter handles rate-limit bursts gracefully.
    _RETRY_MAX_ATTEMPTS = 4
    _RETRY_BASE_DELAY   = 1.0   # seconds
    _RETRY_MAX_DELAY    = 30.0  # seconds

    def __init__(self) -> None:
        self._api_key = self._resolve_api_key()
        # genai.Client exposes async methods via the .aio property.
        # A single client is safe to share across coroutines.
        self._client = genai.Client(api_key=self._api_key)
        self._pool: asyncpg.Pool | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def setup(self) -> None:
        """
        Async initialisation — call once at startup before serving requests.

        asyncpg.create_pool connects eagerly up to min_size and registers the
        pgvector codec on every new connection via the init callback, so vector
        columns are decoded to numpy arrays automatically.
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

    async def close(self) -> None:
        """Release all pooled connections. Call on application shutdown."""
        if self._pool:
            await self._pool.close()

    # ── Public interface ──────────────────────────────────────────────────────

    async def ask(self, question: str, course_name: str) -> str:
        """Retrieve relevant syllabus chunks via RAG and answer the question."""
        department, catalog_number = course_name.strip().split(" ", 1)
        chunks = await self._retrieve(question, department, catalog_number)
        if not chunks:
            return f"No syllabus content found for '{course_name}'."

        prompt = (
            f"The following are the {len(chunks)} most relevant syllabus excerpts for the requested course,\n"
            f"ordered by relevance. Each excerpt is labeled with its full course code, title, instructor,\n"
            f"term, section, delivery mode, units, syllabus URL, and relevance score, followed by the\n"
            f"named section of the syllabus the text was drawn from.\n\n"
            f"{self._format_context(chunks)}\n\n"
            f"Student question: {question}"
        )

        response = await self._with_retry(
            self._client.aio.models.generate_content,
            model=self.GENERATION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
        parts = response.candidates[0].content.parts
        return "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()

    # ── Retry ─────────────────────────────────────────────────────────────────

    async def _with_retry(self, fn, *args, **kwargs):
        """
        Call an async function with exponential backoff + full jitter.

        Retries on any exception (Gemini rate limits, transient network errors).
        Re-raises on the final attempt so the caller sees the real error.

        Full jitter ( random * capped_delay ) avoids thundering-herd re-bursts
        when many concurrent requests hit a rate limit at the same time.
        """
        for attempt in range(self._RETRY_MAX_ATTEMPTS):
            try:
                return await fn(*args, **kwargs)
            except Exception:
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
                task_type="QUESTION_ANSWERING",
                output_dimensionality=768,
            ),
        )
        return self._normalize(result.embeddings[0].values)

    @staticmethod
    def _normalize(values: list[float]) -> np.ndarray:
        """L2-normalise a vector using numpy.

        gemini-embedding-001 only auto-normalises 3072-dim output. For any other
        dimension (768, 1536, …) you must normalise before cosine-similarity search,
        otherwise dot-product and cosine results will be wrong.
        """
        v    = np.array(values)
        norm = np.linalg.norm(v)
        return (v / norm) if norm > 0 else v

    async def _retrieve(self, question: str, department: str, catalog_number: str) -> list[dict]:
        """
        Embed the question then fetch the top-K most similar syllabus chunks.

        The DB connection is acquired only for the duration of the query and
        immediately returned to the pool — it is never held across LLM calls.
        asyncpg passes the numpy embedding directly as a pgvector parameter
        (registered via the init callback in setup()), so no manual string
        serialisation is needed.
        """
        embedding = await self._embed_query(question)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
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
                FROM syllabus_chunk sc
                JOIN section s    ON s.section_id    = sc.section_id
                JOIN course c     ON c.course_id     = s.course_id
                JOIN instructor i ON i.instructor_id = s.instructor_id
                WHERE c.subject        = $2
                  AND c.catalog_number = $3
                ORDER BY sc.embedding <=> $1
                LIMIT $4;
                """,
                embedding, department, catalog_number, self.TOP_K,
            )

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
        return "\n\n---\n\n".join(
            (
                f"[{c['subject']} {c['catalog_number']}: {c['course_title']} | "
                f"Instructor: {c['instructor']} | "
                f"{c['session']} {c['year']} Section {c['section']} | "
                f"Delivery: {c['delivery']} | "
                f"Units: {c['units']} | "
                f"Syllabus: {c['syllabus_url']} | "
                f"Relevance: {c['similarity']:.2f}]\n"
                f"## {c['chunk_title']}\n"
                f"{c['chunk_text']}"
            )
            for c in chunks
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_api_key() -> str:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError("Missing API key. Set GOOGLE_API_KEY in your environment.")
        return key
