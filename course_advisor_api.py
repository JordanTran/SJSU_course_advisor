from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from course_advisor import CourseAdvisor


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Course Advisor API", version="1.0.0")

app.mount("/static", StaticFiles(directory="."), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["POST"],
    allow_headers=["*"],
)

# Lazy-initialise the advisor so syllabi are only fetched on first request
_advisor: CourseAdvisor | None = None

def get_advisor() -> CourseAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = CourseAdvisor()
    return _advisor


# ── Request / response schemas ────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str


class AnswerResponse(BaseModel):
    answer: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AnswerResponse)
def ask(payload: QuestionRequest) -> AnswerResponse:
    """Ask the course advisor a question grounded in the loaded syllabi."""
    advisor = get_advisor()
    answer = advisor.ask(payload.question)
    return AnswerResponse(answer=answer)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return FileResponse("course_advisor_ui.html")
