import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from course_advisor import CourseAdvisor


# Session history stores only prior user inputs, never advisor answers.
SESSION_HISTORY_MAX_QUESTIONS = 5
SESSION_HISTORY_TTL_SECONDS = 6 * 60 * 60


# Lifespan

advisor: CourseAdvisor
query_history: dict[str, list[str]] = {}
session_last_seen: dict[str, float] = {}
history_lock: asyncio.Lock


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialise shared resources on startup; release them on shutdown.

    setup() creates the asyncpg connection pool. Because ask() is now a
    native coroutine, FastAPI runs it directly on the event loop -- no worker
    threads are involved, so no anyio thread-limiter is needed. The DB pool
    is only held during the short vector search, not across the full LLM call,
    so _POOL_MAX_CONN no longer caps overall concurrency.
    """
    global advisor, history_lock
    advisor = CourseAdvisor()
    history_lock = asyncio.Lock()
    await advisor.setup()

    yield

    await advisor.close()


# FastAPI app

app = FastAPI(title="Course Advisor API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# Request / response schemas

class QuestionRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class AnswerResponse(BaseModel):
    answer: str
    session_id: str


class FeedbackRequest(BaseModel):
    session_id: str
    question: str
    answer: str
    is_positive: bool


# Session helpers

def _new_session_id() -> str:
    return str(uuid.uuid4())


def _clean_session_id(value: Optional[str]) -> str:
    cleaned = value.strip() if value else ""
    return cleaned or _new_session_id()


def _prune_expired_sessions(now: float) -> None:
    expired = [
        session_id
        for session_id, last_seen in session_last_seen.items()
        if now - last_seen > SESSION_HISTORY_TTL_SECONDS
    ]
    for session_id in expired:
        query_history.pop(session_id, None)
        session_last_seen.pop(session_id, None)


# Routes

@app.post("/ask", response_model=AnswerResponse)
async def ask(payload: QuestionRequest) -> AnswerResponse:
    """Ask the course advisor a question grounded in syllabus content."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question cannot be empty.")

    session_id = _clean_session_id(payload.session_id)

    async with history_lock:
        now = time.time()
        _prune_expired_sessions(now)
        history = list(query_history.get(session_id, []))
        session_last_seen[session_id] = now

    try:
        answer = await advisor.ask(question, history=history)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    async with history_lock:
        session_history = query_history.setdefault(session_id, [])
        session_history.append(question)
        del session_history[:-SESSION_HISTORY_MAX_QUESTIONS]
        session_last_seen[session_id] = time.time()

    return AnswerResponse(answer=answer, session_id=session_id)


@app.post("/feedback", status_code=204)
async def submit_feedback(payload: FeedbackRequest) -> None:
    """Record a thumbs-up or thumbs-down rating for an advisor answer."""
    if not payload.session_id.strip():
        raise HTTPException(status_code=422, detail="session_id cannot be empty.")
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="question cannot be empty.")
    if not payload.answer.strip():
        raise HTTPException(status_code=422, detail="answer cannot be empty.")

    try:
        await advisor.log_feedback(
            payload.session_id,
            payload.question,
            payload.answer,
            payload.is_positive,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/feedback")
async def list_feedback(
    vote:       Optional[str] = Query(default=None, description="Filter by vote: 'up' or 'down'"),
    search:     Optional[str] = Query(default=None, description="Full-text search on question and answer"),
    session_id: Optional[str] = Query(default=None, description="Filter by session ID (partial match)"),
    limit:  int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0,  ge=0),
):
    """Return feedback rows and aggregate stats for the admin dashboard."""
    if vote is not None and vote not in ("up", "down"):
        raise HTTPException(status_code=422, detail="vote must be 'up' or 'down'.")
    try:
        return await advisor.get_feedback(
            vote=vote, search=search, session_id=session_id, limit=limit, offset=offset
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok"}


# Frontend

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")


@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
