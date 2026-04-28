import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from course_advisor import CourseAdvisor


# ── Lifespan ──────────────────────────────────────────────────────────────────

advisor: CourseAdvisor

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialise shared resources on startup; release them on shutdown.

    setup() creates the asyncpg connection pool. Because ask() is now a
    native coroutine, FastAPI runs it directly on the event loop — no worker
    threads are involved, so no anyio thread-limiter is needed. The DB pool
    is only held during the short vector search, not across the full LLM call,
    so _POOL_MAX_CONN no longer caps overall concurrency.
    """
    global advisor
    advisor = CourseAdvisor()
    await advisor.setup()

    yield

    await advisor.close()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Course Advisor API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Request / response schemas ────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str


class AnswerResponse(BaseModel):
    answer: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AnswerResponse)
async def ask(payload: QuestionRequest) -> AnswerResponse:
    """Ask the course advisor a question grounded in the syllabi for a given course."""
    try:
        answer = await advisor.ask(payload.question)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
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
