import io
import os

import httpx
import psycopg2
from google import genai
from google.genai.types import GenerateContentConfig


class CourseAdvisor:
    """An AI-powered academic advisor grounded in course syllabus documents."""

    DEFAULT_SYSTEM_PROMPT = """\
    You are a helpful academic advisor. You have access to the official course
    syllabus documents provided in every user message. Use their content
    to answer the student's question accurately.

    Rules:
    - Base your answer only on the syllabus content provided.
    - If the syllabi don't cover the question, say so honestly.
    - Be concise, friendly, and clear.
    """

    def __init__(
        self,
        course_name: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
    ) -> None:
        self.course_name = course_name
        self.model = model
        self.temperature = temperature
        self.system_prompt = self.DEFAULT_SYSTEM_PROMPT
        self._client = genai.Client(api_key=self._resolve_api_key())
        self._uploaded_files: list | None = None
        self.syllabus_urls = self._fetch_syllabus_urls()

    # ── Public interface ──────────────────────────────────────────────────────

    def ask(self, question: str) -> str:
        """Send a question and return an answer grounded in the syllabus content."""
        uploaded = self._get_uploaded_files()
        if not uploaded:
            return f"No syllabus documents found for course '{self.course_name}'."

        response = self._client.models.generate_content(
            model=self.model,
            contents=[*uploaded, question],
            config=GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=self.temperature,
            ),
        )
        parts = response.candidates[0].content.parts
        return "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_syllabus_urls(self) -> list[str]:
        """Query the PostgreSQL database for syllabus URLs for the given course."""
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "course_advisor"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT syllabus_url FROM section WHERE course = %s",
                    (self.course_name,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            raise ValueError(
                f"No syllabus URLs found for course '{self.course_name}' in the database."
            )
        return [row[0] for row in rows]

    def _get_uploaded_files(self) -> list:
        """Upload all syllabi to the Files API once and cache the results."""
        if self._uploaded_files is None:
            self._uploaded_files = [
                self._upload(url) for url in self.syllabus_urls
            ]
        return self._uploaded_files

    def _upload(self, url: str):
        """Fetch a URL and upload it to the Files API using its actual mime type."""
        response = httpx.get(url, follow_redirects=True)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "text/html").split(";")[0]
        return self._client.files.upload(
            file=io.BytesIO(response.content),
            config=dict(mime_type=mime_type),
        )

    @staticmethod
    def _resolve_api_key() -> str:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError(
                "Missing API key. Set GOOGLE_API_KEY in your environment.\n"
            )
        return key
