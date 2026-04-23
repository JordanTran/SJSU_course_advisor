# Course Advisor

An AI-powered course advisor chatbot for SJSU. Ask questions about course syllabi grounded in a PostgreSQL database, served through a FastAPI backend and a React + Vite frontend.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL

---

## 1. Database Setup

Follow instructions to install pgvector:
https://github.com/pgvector/pgvector

Create the database and load the schema:

``` bash
psql -U postgres -c "CREATE DATABASE course_advisor;"
psql -U postgres -d course_advisor -f course_advisor_db.sql
```

---

## 2. Environment Variables

In `.env`, fill in your DB_PASSWORD and GOOGLE_API_KEY values.

---

## 3. Install Python Dependencies

Install Python dependencies:

``` bash
pip install -r requirements.txt
```

---

## 4. Populate Database
Download chunks_with_embeddings.csv:
https://drive.google.com/drive/folders/1Ec2DcPqYZegE0JpSzmUZgjR8sEv23tR1?usp=sharing

Run script to populate database tables.

``` bash
python scripts/load_database.py
```

## 5. Frontend

Build the React app:

``` bash
cd frontend
npm install
npm run build
```

---

## 6. Backend

Navigate back to root directory and start the FastAPI server:

```bash
cd ..
uvicorn course_advisor_api:app --reload --env-file .env
```

Then visit `http://localhost:8000` in your browser.
