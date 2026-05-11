"""
Tests for transaction behavior in course_advisor SQL operations.

Covers the repeatable_read transaction used in get_feedback, which must ensure
stats, count, and items queries all observe the same database snapshot.

Run with: pytest transactions_test.py -v
"""
import os
import pytest
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
load_dotenv()

DSN = "dbname={} user={} host={} port={} password={}".format(
    os.getenv("DB_NAME",     "course_advisor_test"),
    os.getenv("DB_USER",     "postgres"),
    os.getenv("DB_HOST",     "localhost"),
    os.getenv("DB_PORT",     "5432"),
    os.getenv("DB_PASSWORD", ""),
)

STATS_SQL = """
    SELECT
        COUNT(*)                                AS total,
        COUNT(*) FILTER (WHERE is_positive)     AS positive,
        COUNT(*) FILTER (WHERE NOT is_positive) AS negative
    FROM feedback
"""
COUNT_SQL = "SELECT COUNT(*) FROM feedback"
ITEMS_SQL = """
    SELECT feedback_id, session_id, question, answer, is_positive, created_at
    FROM   feedback
    ORDER  BY created_at DESC
    LIMIT  %s OFFSET %s
"""
INSERT_SQL = """
    INSERT INTO feedback (session_id, question, answer, is_positive)
    VALUES (%s, %s, %s, %s)
"""


@pytest.fixture
def conn():
    """
    Yields an autocommit=True connection with the feedback table emptied via a
    committed DELETE.  Using autocommit here is intentional: tests in this file
    open their own connections (txn_conn, other) to exercise concurrent /
    isolation behaviour.  Those connections must see a clean baseline, which
    requires the setup DELETE to be committed — an uncommitted delete inside a
    transaction is invisible to every other connection and would leave the
    100 k seed rows visible to txn_conn, breaking every count assertion.
    """
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    with connection.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM pg_tables"
            "  WHERE schemaname = 'public' AND tablename = 'feedback'"
            ")"
        )
        if cur.fetchone()[0]:
            cur.execute("DELETE FROM feedback")
    try:
        yield connection
    finally:
        # Remove any rows committed by this test so the next test starts clean.
        with connection.cursor() as cur:
            cur.execute("DELETE FROM feedback")
        connection.close()


def insert(conn, session_id="s1", question="q", answer="a", is_positive=True):
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, (session_id, question, answer, is_positive))


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_repeatable_read_isolates_concurrent_insert(conn):
    """A concurrent insert committed mid-transaction must not be visible inside it."""
    insert(conn, question="initial")

    results = {}
    with psycopg2.connect(DSN) as txn_conn:
        txn_conn.autocommit = False
        with txn_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute(STATS_SQL)
            results["stats"] = cur.fetchone()

            # Concurrent write on a separate connection
            with psycopg2.connect(DSN) as other:
                other.autocommit = True
                with other.cursor() as oc:
                    oc.execute(INSERT_SQL, ("s2", "concurrent", "a", False))

            cur.execute(COUNT_SQL)
            results["count"] = cur.fetchone()["count"]  # RealDictCursor returns a dict
            cur.execute(ITEMS_SQL, (50, 0))
            results["items"] = cur.fetchall()
        txn_conn.commit()

    assert results["stats"]["total"] == 1
    assert results["count"] == 1
    assert len(results["items"]) == 1


def test_stats_reflect_full_table_not_filter(conn):
    """Stats count the whole table; the filtered items query operates independently."""
    for i, pos in enumerate([True, True, False]):
        insert(conn, session_id=f"s{i}", question=f"q{i}", is_positive=pos)

    with psycopg2.connect(DSN) as txn_conn:
        txn_conn.autocommit = False
        with txn_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute(STATS_SQL)
            stats = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM feedback WHERE is_positive = FALSE")
            filtered_total = cur.fetchone()["count"]
            cur.execute(
                "SELECT feedback_id FROM feedback WHERE is_positive = FALSE"
                " ORDER BY created_at DESC LIMIT %s OFFSET %s", (50, 0)
            )
            items = cur.fetchall()
        txn_conn.commit()

    assert stats["total"] == 3
    assert stats["positive"] == 2
    assert stats["negative"] == 1
    assert filtered_total == 1
    assert len(items) == 1


def test_rollback_on_error(conn):
    """An exception mid-transaction rolls back any writes in that block."""
    try:
        with psycopg2.connect(DSN) as c:
            c.autocommit = False
            with c.cursor() as cur:
                cur.execute(INSERT_SQL, ("s1", "will-rollback", "a", True))
                raise RuntimeError("simulated failure")
    except RuntimeError:
        pass

    with conn.cursor() as cur:
        cur.execute(COUNT_SQL)
        assert cur.fetchone()[0] == 0


def test_committed_insert_is_visible(conn):
    """A committed INSERT is immediately visible in a subsequent query."""
    insert(conn, session_id="s-abc", question="What is grading?", answer="See syllabus.")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM feedback WHERE session_id = %s", ("s-abc",))
        row = cur.fetchone()

    assert row["question"] == "What is grading?"
    assert row["is_positive"] is True


def test_pagination_within_transaction(conn):
    """LIMIT/OFFSET pages consistently inside a repeatable_read transaction."""
    for i in range(5):
        insert(conn, session_id=f"s{i}", question=f"q{i}")

    with psycopg2.connect(DSN) as txn_conn:
        txn_conn.autocommit = False
        with txn_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute(ITEMS_SQL, (3, 0))
            page1 = cur.fetchall()
            cur.execute(ITEMS_SQL, (3, 3))
            page2 = cur.fetchall()
        txn_conn.commit()

    ids1 = {r["feedback_id"] for r in page1}
    ids2 = {r["feedback_id"] for r in page2}
    assert len(page1) == 3
    assert len(page2) == 2
    assert ids1.isdisjoint(ids2)
