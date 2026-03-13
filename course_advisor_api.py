from fastapi import FastAPI, HTTPException
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
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# Cache advisors per course name to avoid re-uploading syllabi on every request
_advisors: dict[str, CourseAdvisor] = {}


def get_advisor(course_name: str) -> CourseAdvisor:
    if course_name not in _advisors:
        _advisors[course_name] = CourseAdvisor(course_name=course_name)
    return _advisors[course_name]


# ── Request / response schemas ────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str
    course_name: str


class AnswerResponse(BaseModel):
    answer: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AnswerResponse)
def ask(payload: QuestionRequest) -> AnswerResponse:
    """Ask the course advisor a question grounded in the syllabi for a given course."""
    try:
        advisor = get_advisor(payload.course_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    answer = advisor.ask(payload.question)
    return AnswerResponse(answer=answer)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return FileResponse("course_advisor_ui.html")
