# SJSU Course Advisor

An AI-powered academic advisor chatbot for San José State University students. Ask natural-language questions about course syllabi and receive grounded, citation-backed answers drawn from a PostgreSQL vector database.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Project Structure](#project-structure)
5. [Environment Variables](#environment-variables)
6. [Database Setup](#database-setup)
7. [Data Pipeline](#data-pipeline)
8. [Python Backend](#python-backend)
9. [Frontend](#frontend)
10. [Running the Application](#running-the-application)
11. [Testing](#testing)
12. [Backup and Recovery](#backup-and-recovery)
13. [API Reference](#api-reference)

---

## Overview

The Course Advisor answers student questions about SJSU course syllabi using a **ReWOO-style agentic architecture**:

- **Planner** — an LLM call that produces a structured JSON retrieval plan
- **Worker** — executes tool calls (vector similarity search against PostgreSQL/pgvector), running dependency-free steps concurrently via `asyncio.gather`
- **Solver** — synthesises evidence into a student-facing answer, citing the original syllabus URLs

Every answer is grounded strictly in official syllabus text; the agent is instructed never to hallucinate beyond what the documents contain.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Browser / Client                     │
│              React + Vite + Tailwind CSS                 │
└────────────────────────┬─────────────────────────────────┘
                         │  HTTP (proxied in dev)
┌────────────────────────▼─────────────────────────────────┐
│               FastAPI  (course_advisor_api.py)           │
│   /ask  /feedback  /admin  – session management, CORS    │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│          CourseAdvisor  (course_advisor.py)              │
│   LangGraph ReWOO: Planner → Worker → Solver             │
│   LLM: Google Gemini via LangChain + google-genai        │
└──────────┬─────────────────────────────┬─────────────────┘
           │ asyncpg                     │ Gemini Embeddings API
┌──────────▼──────────┐       ┌──────────▼──────────┐
│  PostgreSQL +        │       │  Google AI Platform  │
│  pgvector            │       │  (text-embedding-*)  │
│  (syllabus chunks)   │       └─────────────────────┘
└─────────────────────┘
```

**Data pipeline** (one-time setup):
```
scrape_syllabi.py → chunk_syllabi.py → embed_chunks.py → load_database.py
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| PostgreSQL | 14+ with [pgvector](https://github.com/pgvector/pgvector) |
| Google AI API key | [Get one here](https://aistudio.google.com/app/apikey) |

Install pgvector by following the instructions at https://github.com/pgvector/pgvector before proceeding.

---

## Project Structure

```
SJSU_course_advisor/
├── course_advisor.py            # ReWOO agent: Planner, Worker, Solver
├── course_advisor_api.py        # FastAPI app: /ask, /feedback, /admin endpoints
├── course_advisor_db.sql        # PostgreSQL schema (colleges → chunks + feedback)
├── requirements.txt             # Python dependencies
├── .env                         # Environment variables (do not commit)
│
├── frontend/                    # React + Vite + Tailwind UI
│   ├── src/
│   │   ├── App.tsx              # Main chat interface
│   │   ├── AdminPage.tsx        # Feedback review dashboard
│   │   └── components/ui/       # shadcn/ui component library
│   ├── package.json
│   └── vite.config.ts           # Dev proxy: /ask, /health → localhost:8000
│
├── scripts/
│   ├── scrape_syllabi.py        # Playwright scraper for campusconcourse.com
│   ├── chunk_syllabi.py         # Splits syllabus HTML into semantic chunks
│   ├── embed_chunks.py          # Generates 768-dim Gemini embeddings
│   ├── embed_cmpe180b.py        # Targeted embedder for a specific course
│   ├── load_database.py         # Loads chunks_with_embeddings.csv → PostgreSQL
│   ├── course_advisor_db_indexing.sql  # IVFFlat / HNSW vector index definitions
│   ├── feedback_test_data.sql   # Seed data for feedback table tests
│   ├── backup.sh                # pg_dump wrapper
│   └── restore.sh               # Drop-recreate-restore wrapper
│
└── tests/
    ├── course_advisor_test.py              # End-to-end agent smoke test
    ├── course_advisor_test_db_validation.py # pytest suite: schema, data, embeddings
    ├── concurrency_test.py                 # Async load test: burst, ramp, sustain
    ├── indexing_benchmark.py               # EXPLAIN-based index speedup benchmark
    └── indexing_tests.sql                  # SQL queries used by the benchmark
```

---

## Environment Variables

Copy the template and fill in your values:

```bash
cp .env .env.local   # optional: keep a local override
```

`.env` contains:

```ini
DB_HOST=localhost
DB_PORT=5432
DB_NAME=course_advisor
DB_USER=postgres
DB_PASSWORD=YOUR_PASSWORD_HERE

GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY_HERE
```

`GOOGLE_API_KEY` is used both by the backend agent (Gemini LLM + embeddings) and by the data-pipeline scripts. Never commit this file.

---

## Database Setup

### 1. Create the databases

```bash
psql -U postgres -c "CREATE DATABASE course_advisor;"
psql -U postgres -d course_advisor -f course_advisor_db.sql

# Also create the test database used by the validation suite
psql -U postgres -c "CREATE DATABASE course_advisor_test;"
psql -U postgres -d course_advisor_test -f course_advisor_db.sql
```

`course_advisor_db.sql` creates the following schema (all tables are dropped and recreated on each run):

```
college → department → subject → course → section → syllabus_chunk
                                              ↕
                                          instructor (via instructor_department)
                                              ↕
                                           feedback
```

`syllabus_chunk` stores a `vector(768)` column backed by pgvector.

---

## Data Pipeline

Run these steps once to populate the database from scratch. If you have already downloaded the pre-built CSV, skip to step 4.

### Step 1 — Scrape syllabi

Crawls SJSU Campus Concourse for syllabus metadata and URLs (requires Playwright):

```bash
# First-time Playwright setup
playwright install chromium

python scripts/scrape_syllabi.py
# Output: scripts/syllabi_db.csv
```

### Step 2 — Chunk syllabi

Downloads each syllabus HTML page and splits it into semantically coherent text chunks:

```bash
python scripts/chunk_syllabi.py
# Output: scripts/chunks.csv
```

### Step 3 — Generate embeddings

Calls the Google Gemini embedding API to produce 768-dimensional vectors for each chunk:

```bash
python scripts/embed_chunks.py
# Output: scripts/chunks_with_embeddings.csv
```

> This step makes many API calls and may take a while depending on the dataset size. The script includes rate-limit handling.

### Step 4 — Load the database

Download the pre-built CSV (recommended):
[chunks_with_embeddings.csv on Google Drive](https://drive.google.com/drive/folders/1Ec2DcPqYZegE0JpSzmUZgjR8sEv23tR1?usp=sharing)

Place the file at `scripts/chunks_with_embeddings.csv`, then run:

```bash
python scripts/load_database.py
```

This populates all tables (`college`, `department`, `subject`, `course`, `section`, `instructor`, `syllabus_chunk`) and inserts optional feedback seed data.

---

## Python Backend

### Install dependencies

```bash
pip install -r requirements.txt
```

Key packages:

| Package | Purpose |
|---|---|
| `fastapi`, `uvicorn` | ASGI web framework and server |
| `asyncpg`, `pgvector` | Async PostgreSQL driver with vector type support |
| `google-genai` | Google Gemini API (embeddings + LLM) |
| `langchain-google-genai`, `langgraph` | LangChain/LangGraph for the ReWOO agent graph |
| `pydantic` | Request/response schema validation |
| `python-dotenv` | `.env` file loading |
| `beautifulsoup4`, `playwright`, `pandas` | Data pipeline only |

### Start the backend server

```bash
uvicorn course_advisor_api:app --reload --env-file .env
```

The API starts at `http://localhost:8000`. In production, remove `--reload` and set appropriate CORS origins in `course_advisor_api.py`.

**Session behaviour:** Each conversation is assigned a UUID session ID. The server retains up to 5 prior user questions per session (no answers) for follow-up context resolution. Sessions expire after 6 hours of inactivity.

---

## Frontend

### Install and run in development mode

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server starts at `http://localhost:5173` and proxies `/ask` and `/health` to the FastAPI backend at `http://localhost:8000` (configured in `vite.config.ts`).

### Build for production

```bash
cd frontend
npm run build
```

The compiled static assets land in `frontend/dist/`. FastAPI serves them directly — navigate back to the project root and start the server as described above; visiting `http://localhost:8000` loads the built frontend.

### Frontend stack

| Package | Purpose |
|---|---|
| React 19 + TypeScript | UI framework |
| Vite 7 | Build tool and dev server |
| Tailwind CSS 4 | Utility-first styling |
| shadcn/ui + Radix UI | Accessible component primitives |
| react-markdown | Renders markdown in chat responses |
| recharts | Charts on the admin feedback dashboard |
| lucide-react | Icons |

---

## Running the Application

After completing setup, the typical development workflow is:

```bash
# Terminal 1 — backend
uvicorn course_advisor_api:app --reload --env-file .env

# Terminal 2 — frontend dev server (optional; skip if using the built frontend)
cd frontend && npm run dev
```

Then open `http://localhost:5173` (dev) or `http://localhost:8000` (production build).

---

## Testing

### 1. Agent smoke test

Verifies the full Planner → Worker → Solver pipeline against the live database:

```bash
python tests/course_advisor_test.py
```

### 2. Database validation suite

A pytest suite with 8 phases covering connection, schema, row counts, uniqueness, referential integrity, data quality, embedding dimensions, and a full DB ↔ CSV comparison:

```bash
pytest tests/course_advisor_test_db_validation.py -v -s
```

Requires `scripts/chunks_with_embeddings.csv` to be present (used as the ground-truth source).

<img width="1747" height="171" alt="image" src="https://github.com/user-attachments/assets/2dff6c0e-2475-4f56-99c2-196c1b50f09b" />


### 3. Concurrency / load test

Stress-tests the live API with three scenarios — burst, ramp, and sustain — and prints a latency/error summary table:

```bash
# Install extra deps if needed
pip install httpx rich

python tests/concurrency_test.py
```

Configuration constants at the top of the file control concurrency levels (`BURST_N`, `RAMP_MAX`, `SUSTAIN_RPS`, `SUSTAIN_DUR`) and which scenarios to skip (`SKIP_BURST`, `SKIP_RAMP`, `SKIP_SUSTAIN`). The API server must be running before executing this test.

<img width="1462" height="570" alt="image" src="https://github.com/user-attachments/assets/c751fddb-ee8f-4e21-a69c-bf6e40f36f75" />c

### 4. Indexing benchmark

Measures query execution time and I/O block counts with and without vector indexes using `EXPLAIN (ANALYZE, BUFFERS)`:

```bash
python tests/indexing_benchmark.py
```

Prints a Rich table comparing base vs. indexed query performance across multiple scenarios defined in `tests/indexing_tests.sql`.

<img width="1230" height="671" alt="image" src="https://github.com/user-attachments/assets/f0d36f82-30ef-4e64-8f71-91af9ff83ffd" />


---

## Backup and Recovery

### Create a backup

```bash
./scripts/backup.sh
# Saves a timestamped .sql dump to ./backups/
```

### Restore from backup

Download the latest backup if you don't have one:
[course_advisor_db backup on Google Drive](https://drive.google.com/file/d/1tcNZ2MRAvo1QgKhK8Eh9WVrDgaFItKge/view?usp=drive_link)

```bash
./scripts/restore.sh backups/course_advisor_db_2026-04-26_03-21-28.sql
```

The restore script will ask for confirmation before dropping and recreating the database.

---

## API Reference

All endpoints are served by `course_advisor_api.py` at `http://localhost:8000`.

### `POST /ask`

Submit a question and receive an AI-generated answer grounded in syllabus data.

**Request body:**
```json
{
  "question": "What topics are covered in CMPE 180B?",
  "session_id": "optional-uuid-string"
}
```

**Response:**
```json
{
  "answer": "CMPE 180B covers...",
  "session_id": "uuid-assigned-or-echoed"
}
```

### `POST /feedback`

Record a thumbs-up or thumbs-down on a response.

**Request body:**
```json
{
  "session_id": "uuid",
  "question": "What topics are covered in CMPE 180B?",
  "answer": "CMPE 180B covers...",
  "is_positive": true
}
```

### `GET /health`

Returns `{"status": "ok"}` when the server is running.

### `GET /admin`

Returns feedback records with optional filters. Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `is_positive` | bool | Filter by thumbs-up (`true`) or thumbs-down (`false`) |
| `limit` | int | Maximum number of records to return |
| `offset` | int | Pagination offset |
