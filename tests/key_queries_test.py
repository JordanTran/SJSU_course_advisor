"""
Tests for key SQL queries used in course_advisor:
  - Pure vector search (no filters)
  - Filtered vector search via CTE (subject, instructor ILIKE, year/session)
  - Feedback INSERT
  - Feedback stats / count / items queries
  - Feedback chart data (daily aggregation)

Run with: pytest key_queries_test.py -v
"""
import os
import numpy as np
import pytest
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
load_dotenv()

DSN = "dbname={} user={} host={} port={} password={}".format(
    os.getenv("DB_NAME",     "course_advisor_test"),
    os.getenv("DB_USER",     "postgres"),
    os.getenv("DB_HOST",     "localhost"),
    os.getenv("DB_PORT",     "5432"),
    os.getenv("DB_PASSWORD", ""),
)

# ── SQL (mirrors course_advisor._retrieve / get_feedback / get_feedback_chart_data) ──

SELECT_COLS = """
    sc.chunk_id, sc.chunk_title, sc.chunk_text,
    c.subject, c.catalog_number,
    s.course_title, s.units, s.session, s.year, s.section, s.delivery, s.syllabus_url,
    i.instructor_name,
    1 - (sc.embedding <=> %s) AS similarity
"""

PURE_VECTOR_SQL = f"""
    SELECT {SELECT_COLS}
    FROM syllabus_chunk sc
    JOIN section    s ON s.section_id    = sc.section_id
    JOIN course     c ON c.course_id     = s.course_id
    JOIN instructor i ON i.instructor_id = s.instructor_id
    ORDER BY sc.embedding <=> %s
    LIMIT %s
"""

FILTERED_SUBJECT_SQL = f"""
    WITH filtered_ids AS (
        SELECT sc.chunk_id
        FROM syllabus_chunk sc
        JOIN section    s ON s.section_id    = sc.section_id
        JOIN course     c ON c.course_id     = s.course_id
        JOIN instructor i ON i.instructor_id = s.instructor_id
        WHERE c.subject = %s
    )
    SELECT {SELECT_COLS}
    FROM syllabus_chunk sc
    JOIN filtered_ids fi ON fi.chunk_id      = sc.chunk_id
    JOIN section      s  ON s.section_id     = sc.section_id
    JOIN course       c  ON c.course_id      = s.course_id
    JOIN instructor   i  ON i.instructor_id  = s.instructor_id
    ORDER BY sc.embedding <=> %s
    LIMIT %s
"""

FILTERED_INSTRUCTOR_SQL = f"""
    WITH filtered_ids AS (
        SELECT sc.chunk_id
        FROM syllabus_chunk sc
        JOIN section    s ON s.section_id    = sc.section_id
        JOIN course     c ON c.course_id     = s.course_id
        JOIN instructor i ON i.instructor_id = s.instructor_id
        WHERE i.instructor_name ILIKE %s
    )
    SELECT {SELECT_COLS}
    FROM syllabus_chunk sc
    JOIN filtered_ids fi ON fi.chunk_id      = sc.chunk_id
    JOIN section      s  ON s.section_id     = sc.section_id
    JOIN course       c  ON c.course_id      = s.course_id
    JOIN instructor   i  ON i.instructor_id  = s.instructor_id
    ORDER BY sc.embedding <=> %s
    LIMIT %s
"""

FILTERED_YEAR_SESSION_SQL = f"""
    WITH filtered_ids AS (
        SELECT sc.chunk_id
        FROM syllabus_chunk sc
        JOIN section    s ON s.section_id    = sc.section_id
        JOIN course     c ON c.course_id     = s.course_id
        JOIN instructor i ON i.instructor_id = s.instructor_id
        WHERE s.year = %s AND s.session = %s
    )
    SELECT {SELECT_COLS}
    FROM syllabus_chunk sc
    JOIN filtered_ids fi ON fi.chunk_id      = sc.chunk_id
    JOIN section      s  ON s.section_id     = sc.section_id
    JOIN course       c  ON c.course_id      = s.course_id
    JOIN instructor   i  ON i.instructor_id  = s.instructor_id
    ORDER BY sc.embedding <=> %s
    LIMIT %s
"""

FEEDBACK_INSERT_SQL = """
    INSERT INTO feedback (session_id, question, answer, is_positive)
    VALUES (%s, %s, %s, %s)
"""
STATS_SQL = """
    SELECT
        COUNT(*)                                AS total,
        COUNT(*) FILTER (WHERE is_positive)     AS positive,
        COUNT(*) FILTER (WHERE NOT is_positive) AS negative
    FROM feedback
"""
ITEMS_SQL = """
    SELECT feedback_id, session_id, question, answer, is_positive, created_at
    FROM   feedback
    ORDER  BY created_at DESC
    LIMIT  %s OFFSET %s
"""
SEARCH_ITEMS_SQL = """
    SELECT feedback_id, question, answer
    FROM   feedback
    WHERE  question ILIKE %s OR answer ILIKE %s
    ORDER  BY created_at DESC
    LIMIT  %s OFFSET %s
"""
CHART_SQL = """
    SELECT
        created_at::date                        AS day,
        COUNT(*)                                AS total,
        COUNT(*) FILTER (WHERE is_positive)     AS positive
    FROM   feedback
    GROUP  BY day
    ORDER  BY day ASC
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def unit_vec(i, dim=768):
    """Return a 768-dim unit vector with 1.0 at position i (orthogonal test vectors)."""
    v = np.zeros(dim)
    v[i] = 1.0
    return v


def seed_chunk(conn, subject="CS", catalog_number="146",
               instructor_name="Dr. Smith", year=2025,
               session="Spring", delivery="In Person", embedding=None):
    """
    Insert the full parent chain (college → department → subject → course,
    instructor) and return the new chunk_id. Uses ON CONFLICT DO NOTHING so
    multiple seeds in one test can share the same course/section.
    """
    if embedding is None:
        embedding = unit_vec(0)

    with conn.cursor() as cur:
        # college / department / subject — shared across seeds; ignore duplicates
        cur.execute(
            "INSERT INTO college (college_name) VALUES ('Test College') ON CONFLICT DO NOTHING"
        )
        cur.execute("SELECT college_id FROM college WHERE college_name = 'Test College'")
        college_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO department (dept_name, college_id) VALUES ('Test Dept', %s) ON CONFLICT DO NOTHING",
            (college_id,)
        )
        cur.execute("SELECT dept_id FROM department WHERE dept_name = 'Test Dept'")
        dept_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO subject (subject, subject_name, dept_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (subject, subject, dept_id)
        )

        # course
        cur.execute(
            "INSERT INTO course (subject, catalog_number) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (subject, catalog_number)
        )
        cur.execute(
            "SELECT course_id FROM course WHERE subject = %s AND catalog_number = %s",
            (subject, catalog_number)
        )
        course_id = cur.fetchone()[0]

        # instructor
        cur.execute(
            "INSERT INTO instructor (instructor_name) VALUES (%s) ON CONFLICT DO NOTHING",
            (instructor_name,)
        )
        cur.execute(
            "SELECT instructor_id FROM instructor WHERE instructor_name = %s",
            (instructor_name,)
        )
        instructor_id = cur.fetchone()[0]

        # section — reuse if the same (course, year, session, section) already exists
        cur.execute(
            """INSERT INTO section
                   (course_id, course_title, units, year, session, section,
                    instructor_id, syllabus_url, delivery)
               VALUES (%s, 'Test Course', 3, %s, %s, '01', %s, 'http://example.com', %s)
               ON CONFLICT DO NOTHING""",
            (course_id, year, session, instructor_id, delivery)
        )
        cur.execute(
            "SELECT section_id FROM section WHERE course_id=%s AND year=%s AND session=%s AND section='01'",
            (course_id, year, session)
        )
        section_id = cur.fetchone()[0]

        # chunk — always a new row
        cur.execute(
            """INSERT INTO syllabus_chunk (section_id, chunk_title, chunk_text, embedding)
               VALUES (%s, 'Grading', '40%% exams, 60%% projects.', %s)
               RETURNING chunk_id""",
            (section_id, embedding)
        )
        return cur.fetchone()[0]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    """
    Yields a psycopg2 connection whose transaction is always rolled back after
    the test, keeping the shared test DB clean regardless of pass/fail.

    Also issues a DELETE on the feedback table at the start of each test so
    stats/count assertions always see exactly the rows the test itself inserts.
    The delete is part of the same transaction and is therefore also rolled back,
    leaving pre-existing feedback rows intact for other test runs.
    """
    connection = psycopg2.connect(DSN)
    connection.autocommit = False
    register_vector(connection)
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM pg_tables"
                "  WHERE schemaname = 'public' AND tablename = 'feedback'"
                ")"
            )
            if cur.fetchone()[0]:
                cur.execute("DELETE FROM feedback")
        yield connection
    finally:
        connection.rollback()
        connection.close()


# ── Pure vector search ────────────────────────────────────────────────────────

def test_pure_vector_search_returns_closest(conn):
    """Top-1 result is the chunk with highest cosine similarity to the query."""
    seed_chunk(conn, subject="CS",   embedding=unit_vec(0))
    seed_chunk(conn, subject="MATH", embedding=unit_vec(1))

    query = unit_vec(0)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(PURE_VECTOR_SQL, (query, query, 1))
        rows = cur.fetchall()

    assert len(rows) == 1
    assert rows[0]["subject"] == "CS"
    assert float(rows[0]["similarity"]) == pytest.approx(1.0, abs=1e-5)


def test_pure_vector_search_respects_limit(conn):
    """LIMIT (TOP_K) caps the number of returned rows."""
    for _ in range(5):
        seed_chunk(conn)  # all land in the same section; 5 distinct chunks

    query = unit_vec(0)
    with conn.cursor() as cur:
        cur.execute(PURE_VECTOR_SQL, (query, query, 3))
        assert len(cur.fetchall()) == 3


def test_pure_vector_search_includes_metadata(conn):
    """Result rows expose all metadata columns needed by _retrieve."""
    seed_chunk(conn)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(PURE_VECTOR_SQL, (unit_vec(0), unit_vec(0), 3))
        row = cur.fetchone()

    for col in ("chunk_id", "chunk_title", "chunk_text", "subject", "catalog_number",
                "course_title", "units", "session", "year", "section",
                "delivery", "syllabus_url", "instructor_name", "similarity"):
        assert col in row, f"Missing column: {col}"


# ── Filtered vector search (CTE) ──────────────────────────────────────────────

def test_filtered_by_subject_excludes_others(conn):
    """CTE subject filter returns only chunks matching that subject."""
    cs_id   = seed_chunk(conn, subject="CS",   embedding=unit_vec(0))
    math_id = seed_chunk(conn, subject="MATH", embedding=unit_vec(1))

    # Query is closer to MATH but filter restricts to CS.
    # Use a large limit so real DB rows don't crowd out seeded ones.
    query = unit_vec(1)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(FILTERED_SUBJECT_SQL, ("CS", query, query, 10000))
        rows = cur.fetchall()

    ids = {r["chunk_id"] for r in rows}
    assert cs_id   in ids,     "seeded CS chunk must appear"
    assert math_id not in ids, "seeded MATH chunk must be excluded"
    assert all(r["subject"] == "CS" for r in rows), "every row must be CS"


def test_filtered_by_subject_empty_when_no_match(conn):
    """CTE filter excludes the seeded chunk when the subject filter doesn't match it."""
    cs_id = seed_chunk(conn, subject="CS")

    # Use a made-up subject that cannot exist in the real DB.
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(FILTERED_SUBJECT_SQL, ("ZZZNOTREAL", unit_vec(0), unit_vec(0), 10000))
        rows = cur.fetchall()

    assert cs_id not in {r["chunk_id"] for r in rows}
    assert all(r["subject"] == "ZZZNOTREAL" for r in rows)  # vacuously true if empty


def test_filtered_by_instructor_ilike(conn):
    """Instructor ILIKE filter matches partial, case-insensitive names."""
    alice_id = seed_chunk(conn, subject="CS",   catalog_number="146", instructor_name="Dr. Alice Wang")
    bob_id   = seed_chunk(conn, subject="MATH", catalog_number="32",  instructor_name="Prof. Bob Kim")

    # Use a large limit so real DB rows don't crowd out the seeded one.
    query = unit_vec(0)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(FILTERED_INSTRUCTOR_SQL, ("%alice%", query, query, 10000))
        rows = cur.fetchall()

    ids = {r["chunk_id"] for r in rows}
    assert alice_id in ids,     "seeded Alice chunk must appear"
    assert bob_id   not in ids, "seeded Bob chunk must be excluded"
    assert all("alice" in r["instructor_name"].lower() for r in rows), \
        "every row must have 'alice' in instructor_name"


def test_filtered_by_year_and_session(conn):
    """Year and session filters exclude chunks from other terms."""
    spring_id = seed_chunk(conn, subject="CS",   catalog_number="146", year=2025, session="Spring")
    fall_id   = seed_chunk(conn, subject="MATH", catalog_number="32",  year=2024, session="Fall")

    # Use a large limit so real DB rows don't crowd out the seeded one.
    query = unit_vec(0)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(FILTERED_YEAR_SESSION_SQL, (2025, "Spring", query, query, 10000))
        rows = cur.fetchall()

    ids = {r["chunk_id"] for r in rows}
    assert spring_id in ids,     "seeded Spring 2025 chunk must appear"
    assert fall_id   not in ids, "seeded Fall 2024 chunk must be excluded"
    assert all(r["year"] == 2025 and r["session"] == "Spring" for r in rows), \
        "every row must be Spring 2025"


# ── Feedback INSERT ────────────────────────────────────────────────────────────

def test_feedback_insert_persists_all_fields(conn):
    """log_feedback INSERT stores all fields correctly."""
    with conn.cursor() as cur:
        cur.execute(FEEDBACK_INSERT_SQL, ("sess-1", "What is grading?", "See syllabus.", True))

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM feedback WHERE session_id = %s", ("sess-1",))
        row = cur.fetchone()

    assert row["question"]    == "What is grading?"
    assert row["answer"]      == "See syllabus."
    assert row["is_positive"] is True
    assert row["created_at"]  is not None


# ── Feedback stats ─────────────────────────────────────────────────────────────

def test_feedback_stats_counts(conn):
    """Stats query tallies total, positive, and negative correctly."""
    with conn.cursor() as cur:
        for i, pos in enumerate([True, True, False]):
            cur.execute(FEEDBACK_INSERT_SQL, (f"s{i}", f"q{i}", "a", pos))

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(STATS_SQL)
        stats = cur.fetchone()

    assert stats["total"]    == 3
    assert stats["positive"] == 2
    assert stats["negative"] == 1


def test_feedback_stats_empty_table(conn):
    """Stats query returns zeros on an empty feedback table."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(STATS_SQL)
        stats = cur.fetchone()

    assert stats["total"] == 0
    assert stats["positive"] == 0
    assert stats["negative"] == 0


def test_feedback_items_ordered_newest_first(conn):
    """Items query orders rows newest-first."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO feedback (session_id, question, answer, is_positive, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            ("s1", "first", "a", True, "2025-01-01T00:00:00+00"),
        )
        cur.execute(
            "INSERT INTO feedback (session_id, question, answer, is_positive, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            ("s2", "second", "a", True, "2025-01-02T00:00:00+00"),
        )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(ITEMS_SQL, (50, 0))
        rows = cur.fetchall()

    assert rows[0]["question"] == "second"
    assert rows[1]["question"] == "first"


def test_feedback_search_ilike(conn):
    """ILIKE search matches substrings in question or answer, case-insensitively."""
    with conn.cursor() as cur:
        cur.execute(FEEDBACK_INSERT_SQL, ("s1", "What is grading policy?", "a", True))
        cur.execute(FEEDBACK_INSERT_SQL, ("s2", "Tell me about attendance", "a", True))

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(SEARCH_ITEMS_SQL, ("%GRADING%", "%GRADING%", 50, 0))
        rows = cur.fetchall()

    assert len(rows) == 1
    assert "grading" in rows[0]["question"].lower()


# ── Feedback chart ─────────────────────────────────────────────────────────────

def test_feedback_chart_groups_by_day(conn):
    """Chart query returns one row per day, oldest-first."""
    with conn.cursor() as cur:
        for ts, pos in [
            ("2025-03-01T09:00:00+00", True),
            ("2025-03-01T17:00:00+00", False),
            ("2025-03-02T10:00:00+00", True),
        ]:
            cur.execute(
                "INSERT INTO feedback (session_id, question, answer, is_positive, created_at)"
                " VALUES (%s,%s,%s,%s,%s)",
                ("s", "q", "a", pos, ts),
            )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(CHART_SQL)
        rows = cur.fetchall()

    assert len(rows) == 2
    assert rows[0]["total"]    == 2  # March 1
    assert rows[0]["positive"] == 1
    assert rows[1]["total"]    == 1  # March 2
    assert rows[1]["positive"] == 1
    assert rows[0]["day"] < rows[1]["day"]


def test_feedback_chart_empty_table(conn):
    """Chart query returns no rows when the feedback table is empty."""
    with conn.cursor() as cur:
        cur.execute(CHART_SQL)
        assert cur.fetchall() == []
