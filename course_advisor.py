import os

import psycopg2
from google import genai
from google.genai import types
from pgvector.psycopg2 import register_vector


class CourseAdvisor:
    """An AI-powered academic advisor grounded in course syllabus documents via RAG."""

    SYSTEM_PROMPT = """\
    You are a helpful academic advisor for students at San José State University.
    You have been given the most relevant excerpts from official course syllabus
    documents across one or more sections of the requested course.

    Rules:
    - Base your answer only on the syllabus excerpts provided.
    - If information varies across sections (e.g. different instructors or semesters),
    acknowledge the differences rather than generalizing.
    - If the excerpts don't cover the question, say so honestly.
    - Be concise, friendly, and clear.
    """

    EMBEDDING_MODEL = "gemini-embedding-001"
    GENERATION_MODEL = "gemini-2.5-flash"
    TOP_K = 5

    def __init__(self) -> None:
        self._client = genai.Client(api_key=self._resolve_api_key())
        self._db_conn = self._connect_db()

    # ── Public interface ──────────────────────────────────────────────────────

    def ask(self, question: str, course_name: str) -> str:
        """Retrieve relevant syllabus chunks via RAG and answer the question."""
        department, catalog_number = course_name.strip().split(" ", 1)
        chunks = self._retrieve(question, department, catalog_number)
        if not chunks:
            return f"No syllabus content found for '{course_name}'."

        prompt = (
            f"The following are syllabus excerpts from one or more sections of the requested course.\n"
            f"Each excerpt is labeled with its course title, instructor, term, section, delivery mode, and units.\n\n"
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

    # ── RAG ───────────────────────────────────────────────────────────────────

    def _embed_query(self, text: str) -> list[float]:
        result = self._client.models.embed_content(
            model=self.EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        return result.embeddings[0].values

    def _retrieve(self, question: str, department: str, catalog_number: str) -> list[dict]:
        vector_str = "[" + ",".join(str(v) for v in self._embed_query(question)) + "]"

        with self._db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    sc.chunk_id,
                    sc.chunk_text,
                    c.course_title,
                    c.units,
                    i.instructor_name,
                    s.session,
                    s.year,
                    s.section,
                    s.delivery,
                    1 - (sc.embedding <=> %s::vector) AS similarity
                FROM syllabus_chunk sc
                JOIN section s    ON s.section_id    = sc.section_id
                JOIN course c     ON c.course_id     = s.course_id
                JOIN instructor i ON i.instructor_id = s.instructor_id
                WHERE c.department     = %s
                  AND c.catalog_number = %s
                ORDER BY sc.embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector_str, department, catalog_number, vector_str, self.TOP_K),
            )
            rows = cur.fetchall()

        return [
            {
                "chunk_id":     row[0],
                "chunk_text":   row[1],
                "course_title": row[2],
                "units":        row[3],
                "instructor":   row[4],
                "session":      row[5],
                "year":         row[6],
                "section":      row[7],
                "delivery":     row[8],
                "similarity":   row[9],
            }
            for row in rows
        ]

    def _format_context(self, chunks: list[dict]) -> str:
        return "\n\n---\n\n".join(
            (
                f"[{c['course_title']} | "
                f"Instructor: {c['instructor']} | "
                f"{c['session']} {c['year']} Section {c['section']} | "
                f"Delivery: {c['delivery']} | "
                f"Units: {c['units']}]\n"
                f"{c['chunk_text']}"
            )
            for c in chunks
        )

    # ── DB ────────────────────────────────────────────────────────────────────

    def _connect_db(self):
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "course_advisor"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            options="-c client_encoding=UTF8",
        )
        register_vector(conn)
        return conn

    @staticmethod
    def _resolve_api_key() -> str:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError("Missing API key. Set GOOGLE_API_KEY in your environment.")
        return key