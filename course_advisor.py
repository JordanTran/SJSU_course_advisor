import io
import os

import httpx
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
        syllabus_urls: list[str],
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
    ) -> None:
        """
        Args:
            syllabus_urls: One or more URLs pointing to course syllabi (PDF or HTML).
        """
        self.syllabus_urls = syllabus_urls
        self.model = model
        self.temperature = temperature
        self.system_prompt = self.DEFAULT_SYSTEM_PROMPT
        self._client = genai.Client(api_key=self._resolve_api_key())
        self._uploaded_files: list | None = None

    # ── Public interface ──────────────────────────────────────────────────────

    def ask(self, question: str) -> str:
        """Send a question and return an answer grounded in the syllabus content."""
        response = self._client.models.generate_content(
            model=self.model,
            contents=[*self._get_uploaded_files(), question],
            config=GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=self.temperature,
            ),
        )
        parts = response.candidates[0].content.parts
        return "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()

    def chat(self) -> None:
        """Start an interactive command-line session."""
        print("\n📚 Course Advisor  (type 'quit' to exit)")
        print("─" * 45)

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue
            if user_input.lower() in {"quit", "exit", "q"}:
                print("Goodbye!")
                break

            print("Course Advisor: ", end="", flush=True)
            try:
                print(self.ask(user_input))
            except Exception as e:
                print(f"[Error] {e}")
            print()

    # ── Private helpers ───────────────────────────────────────────────────────

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