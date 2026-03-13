# Course Advisor

An AI-powered course advisor chatbot for SJSU. Ask questions about course syllabi grounded in a PostgreSQL database, served through a FastAPI backend and a React + Vite frontend.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL

---

## 1. Database Setup

Create the database and load the schema:

``` bash
psql -U postgres -c "CREATE DATABASE course_advisor;"
psql -U postgres -d course_advisor -f course_advisor_db.sql
```

---

## 2. Environment Variables

In `.env`, fill in your DB_PASSWORD and GOOGLE_API_KEY values.

---

## 3. Frontend

### Production (recommended)

Build the React app:

``` bash
cd frontend
npm install
npm run build
```

---

## 3. Backend

Install Python dependencies and start the FastAPI server:

``` bash
pip install -r requirements.txt
uvicorn course_advisor_api:app --reload --env-file .env
```

Then visit `http://localhost:8000` in your browser.

---

## Project Structure

```
course_advisor/
├── course_advisor.py        # Core advisor logic (Gemini + DB)
├── course_advisor_api.py    # FastAPI app & routes
├── course_advisor_db.sql    # Database schema
├── requirements.txt
├── .env                     # Environment variables (never commit)
└── frontend/                # React + Vite + shadcn/ui
    ├── src/
    │   ├── App.tsx           # Main chat UI
    │   └── components/ui/   # shadcn components
    ├── dist/                 # Built output (after npm run build)
    └── vite.config.ts
```
