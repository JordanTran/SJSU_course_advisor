import os
 
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
 
from course_advisor import CourseAdvisor
 
 
# ── FastAPI app ───────────────────────────────────────────────────────────────
 
app = FastAPI(title="Course Advisor API", version="1.0.0")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
 
advisor = CourseAdvisor()
 
 
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
        answer = advisor.ask(payload.question, payload.course_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return AnswerResponse(answer=answer)
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
 
# ── Frontend ──────────────────────────────────────────────────────────────────
 
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
 
app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")
 
 
@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
 
 
@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
