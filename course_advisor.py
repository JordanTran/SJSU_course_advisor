import os
 
import psycopg2
from google import genai
from google.genai import types
from pgvector.psycopg2 import register_vector
 
 
class CourseAdvisor:
    """An AI-powered academic advisor grounded in course syllabus documents via RAG."""
 
    SYSTEM_PROMPT = """\
    You are a helpful academic advisor. You have been given the most relevant
    excerpts from the official course syllabus documents.
 
    Rules:
    - Base your answer only on the syllabus excerpts provided.
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
        chunks = self._retrieve(question, course_name)
        if not chunks:
            return f"No syllabus content found for course '{course_name}'."
 
        prompt = f"Syllabus excerpts:\n{self._format_context(chunks)}\n\nStudent question: {question}"
 
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
 
    def _retrieve(self, question: str, course_name: str) -> list[dict]:
        vector_str = "[" + ",".join(str(v) for v in self._embed_query(question)) + "]"
 
        with self._db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    sc.chunk_text,
                    s.course,
                    1 - (sc.embedding <=> %s::vector) AS similarity
                FROM syllabus_chunks sc
                JOIN section s ON s.section_id = sc.section_id
                WHERE s.course = %s
                ORDER BY sc.embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector_str, course_name, vector_str, self.TOP_K),
            )
            rows = cur.fetchall()
 
        return [
            {"chunk_text": row[0], "course": row[1], "similarity": row[2]}
            for row in rows
        ]
 
    def _format_context(self, chunks: list[dict]) -> str:
        return "\n\n---\n\n".join(
            f"[Excerpt {i} | similarity: {c['similarity']:.2f}]\n{c['chunk_text']}"
            for i, c in enumerate(chunks, 1)
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
 
 
# ── Example usage ─────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    advisor = CourseAdvisor()
    questions = [
        "What is the grading breakdown for this course?",
        "What is the AI policy?",
        "When is the project proposal due?",
    ]
    for q in questions:
        print(f"Q: {q}")
        print(f"A: {advisor.ask(q, course_name='ISE 201')}\n")
