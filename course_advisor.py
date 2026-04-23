import os
from contextlib import contextmanager

import numpy as np
from psycopg2 import pool as pg_pool
from google import genai
from google.genai import types
from pgvector.psycopg2 import register_vector


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

    EMBEDDING_MODEL = "gemini-embedding-001"
    GENERATION_MODEL = "gemini-3-flash-preview"
    TOP_K = 5

    # Pool size bounds — tune to your Postgres max_connections budget.
    _POOL_MIN_CONN = 2
    _POOL_MAX_CONN = 10

    def __init__(self) -> None:
        self._client = genai.Client(api_key=self._resolve_api_key())
        self._pool = self._create_pool()

    # ── Public interface ──────────────────────────────────────────────────────

    def ask(self, question: str, course_name: str) -> str:
        """Retrieve relevant syllabus chunks via RAG and answer the question."""
        department, catalog_number = course_name.strip().split(" ", 1)
        chunks = self._retrieve(question, department, catalog_number)
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

        response = self._client.models.generate_content(
            model=self.GENERATION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
        parts = response.candidates[0].content.parts
        return "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()

    def close(self) -> None:
        """Release all pooled connections. Call on application shutdown."""
        self._pool.closeall()

    # ── RAG ───────────────────────────────────────────────────────────────────

    def _embed_query(self, text: str) -> list[float]:
        result = self._client.models.embed_content(
            model=self.EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="QUESTION_ANSWERING",
                output_dimensionality=768,
            ),
        )
        return self._normalize(result.embeddings[0].values)

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        """L2-normalise a vector using numpy.

        gemini-embedding-001 only auto-normalises 3072-dim output. For any other
        dimension (768, 1536, …) you must normalise before cosine-similarity search,
        otherwise dot-product and cosine results will be wrong.
        """
        v    = np.array(values)
        norm = np.linalg.norm(v)
        return (v / norm).tolist() if norm > 0 else values

    def _retrieve(self, question: str, department: str, catalog_number: str) -> list[dict]:
        vector_str = "[" + ",".join(str(v) for v in self._embed_query(question)) + "]"

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
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
                        1 - (sc.embedding <=> %s::vector) AS similarity
                    FROM syllabus_chunk sc
                    JOIN section s    ON s.section_id    = sc.section_id
                    JOIN course c     ON c.course_id     = s.course_id
                    JOIN instructor i ON i.instructor_id = s.instructor_id
                    WHERE c.subject        = %s
                    AND c.catalog_number = %s
                    ORDER BY sc.embedding <=> %s::vector
                    LIMIT %s;
                    """,
                    (vector_str, department, catalog_number, vector_str, self.TOP_K),
                )
                rows = cur.fetchall()

        return [
            {
                "chunk_id":       row[0],
                "chunk_title":    row[1],
                "chunk_text":     row[2],
                "subject":        row[3],
                "catalog_number": row[4],
                "course_title":   row[5],
                "units":          row[6],
                "session":        row[7],
                "year":           row[8],
                "section":        row[9],
                "delivery":       row[10],
                "syllabus_url":   row[11],
                "instructor":     row[12],
                "similarity":     row[13],
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

    # ── DB ────────────────────────────────────────────────────────────────────

    def _create_pool(self) -> pg_pool.ThreadedConnectionPool:
        """
        Create a thread-safe connection pool.

        ThreadedConnectionPool uses a lock internally so that getconn/putconn
        are safe to call from multiple threads simultaneously — unlike a bare
        psycopg2 connection, which must never be shared across threads.
        """
        return pg_pool.ThreadedConnectionPool(
            minconn=self._POOL_MIN_CONN,
            maxconn=self._POOL_MAX_CONN,
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "course_advisor"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            options="-c client_encoding=UTF8",
        )

    @contextmanager
    def _get_connection(self):
        """
        Borrow a connection from the pool for the duration of a with-block,
        then return it — even if an exception is raised.

        register_vector is called on every checkout because psycopg2's pool
        creates connections lazily and provides no post-connect hook. It is
        idempotent, so calling it on recycled connections is safe.

        Usage:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(...)
        """
        conn = self._pool.getconn()
        register_vector(conn)  # idempotent; ensures vector type is registered
        try:
            yield conn
            conn.commit()          # no-op for read-only queries, harmless
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)   # always returned to the pool

    @staticmethod
    def _resolve_api_key() -> str:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError("Missing API key. Set GOOGLE_API_KEY in your environment.")
        return key
