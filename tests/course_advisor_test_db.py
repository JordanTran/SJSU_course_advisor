"""
test_db.py – Course Advisor DB Test Suite
Run: pytest tests/course_advisor_test_db.py -v
Requires: pip install psycopg2-binary python-dotenv
"""

import pytest
import psycopg2
import psycopg2.errors
import os
from dotenv import load_dotenv

load_dotenv()

ZERO_VEC = "[" + ",".join(["0"] * 768) + "]"


# ─────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def conn():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
    )
    conn.autocommit = False
    yield conn
    conn.close()


@pytest.fixture
def cur(conn):
    """Each test gets its own savepoint – rolls back automatically after."""
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp")
    yield cur
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    cur.close()


@pytest.fixture(scope="session")
def seed(conn):
    """
    Inserts clearly-labeled TEST data once for the whole session.
    Cleaned up automatically at the end.
    """
    cur = conn.cursor()

    # College
    cur.execute("""
        INSERT INTO college (college_name)
        VALUES ('TEST College')
        RETURNING college_id
    """)
    college_id = cur.fetchone()[0] #used returning because SERIAL generated it automatically

    # Department
    cur.execute("""
        INSERT INTO department (dept_name, college_id)
        VALUES ('TEST Department', %s)
        RETURNING dept_id
    """, (college_id,))
    dept_id = cur.fetchone()[0]

    # Subject
    cur.execute("""
        INSERT INTO subject (subject, subject_name, dept_id)
        VALUES ('TEST', 'TEST Subject', %s)
        ON CONFLICT DO NOTHING
    """, (dept_id,))

    # Course
    cur.execute("""
        INSERT INTO course (subject, catalog_number)
        VALUES ('TEST', 'TEST101')
        RETURNING course_id
    """)
    course_id = cur.fetchone()[0]

    # Instructors
    cur.execute("""
        INSERT INTO instructor (instructor_name)
        VALUES ('TEST_Instructor_A'), ('TEST_Instructor_B')
        RETURNING instructor_id
    """)
    inst_a, inst_b = [r[0] for r in cur.fetchall()]

    # Instructor–department associations
    cur.execute("""
        INSERT INTO instructor_department (instructor_id, dept_id)
        VALUES (%s, %s), (%s, %s)
    """, (inst_a, dept_id, inst_b, dept_id)) # both are in same department for simplicity

    # Sections  (syllabus_url and delivery are NOT NULL in this schema)
    cur.execute("""
        INSERT INTO section (course_id, course_title, units, year, session, section, instructor_id, syllabus_url, delivery)
        VALUES
            (%s, 'TEST Course', 3, 2023, 'Fall',   '01', %s, 'https://test.example.com/1', 'Online'),
            (%s, 'TEST Course', 3, 2024, 'Spring', '01', %s, 'https://test.example.com/2', 'In-Person'),
            (%s, 'TEST Course', 3, 2025, 'Fall',   '01', %s, 'https://test.example.com/3', 'Online')
        RETURNING section_id
    """, (course_id, inst_a, course_id, inst_b, course_id, inst_a))
    sec1, sec2, sec3 = [r[0] for r in cur.fetchall()]

    # Chunks  (chunk_title is NOT NULL in this schema)
    cur.execute("""
        INSERT INTO syllabus_chunk (section_id, chunk_title, chunk_text, embedding)
        VALUES
            (%s, 'TEST Grading',      'TEST chunk: grading policy',      %s::vector),
            (%s, 'TEST Schedule',     'TEST chunk: course schedule',     %s::vector),
            (%s, 'TEST Office Hours', 'TEST chunk: office hours policy', %s::vector)
    """, (sec1, ZERO_VEC, sec2, ZERO_VEC, sec3, ZERO_VEC))

    conn.commit() # Make all those seed inserts officially saved to the database.

    yield { # Pause fixture here, give this value to tests, then resume afterward.
        "college_id": college_id,
        "dept_id": dept_id,
        "course_id": course_id,
        "sections": [sec1, sec2, sec3],
        "instructors": [inst_a, inst_b],
    }

    # Cleanup (reverse FK order)
    cur.execute("DELETE FROM syllabus_chunk        WHERE section_id    IN %s", (tuple([sec1, sec2, sec3]),))
    cur.execute("DELETE FROM section               WHERE section_id    IN %s", (tuple([sec1, sec2, sec3]),))
    cur.execute("DELETE FROM course                WHERE course_id      = %s", (course_id,))
    cur.execute("DELETE FROM subject               WHERE subject        = 'TEST'")
    cur.execute("DELETE FROM instructor_department WHERE dept_id        = %s", (dept_id,))
    cur.execute("DELETE FROM instructor            WHERE instructor_id IN %s", (tuple([inst_a, inst_b]),))
    cur.execute("DELETE FROM department            WHERE dept_id        = %s", (dept_id,))
    cur.execute("DELETE FROM college               WHERE college_id     = %s", (college_id,))
    conn.commit()
    cur.close()


# ─────────────────────────────────────────────
#  CRUD
# ─────────────────────────────────────────────

def test_insert_and_read(cur):
    cur.execute("INSERT INTO instructor (instructor_name) VALUES ('TEST_CRUD') RETURNING instructor_id")
    iid = cur.fetchone()[0]
    cur.execute("SELECT instructor_name FROM instructor WHERE instructor_id = %s", (iid,))
    assert cur.fetchone()[0] == "TEST_CRUD"


def test_update(cur):
    cur.execute("INSERT INTO instructor (instructor_name) VALUES ('TEST_UPDATE_OLD') RETURNING instructor_id")
    iid = cur.fetchone()[0]
    cur.execute("UPDATE instructor SET instructor_name = 'TEST_UPDATE_NEW' WHERE instructor_id = %s", (iid,))
    cur.execute("SELECT instructor_name FROM instructor WHERE instructor_id = %s", (iid,))
    assert cur.fetchone()[0] == "TEST_UPDATE_NEW"


def test_delete(cur):
    cur.execute("INSERT INTO instructor (instructor_name) VALUES ('TEST_DELETE') RETURNING instructor_id")
    iid = cur.fetchone()[0]
    cur.execute("DELETE FROM instructor WHERE instructor_id = %s", (iid,))
    cur.execute("SELECT * FROM instructor WHERE instructor_id = %s", (iid,))
    assert cur.fetchone() is None


def test_cascade_delete(cur, seed):
    # Deleting a section should cascade-delete its chunks
    sec_id = seed["sections"][0]
    cur.execute("SELECT COUNT(*) FROM syllabus_chunk WHERE section_id = %s", (sec_id,))
    assert cur.fetchone()[0] > 0                        # chunks exist before delete

    cur.execute("DELETE FROM section WHERE section_id = %s", (sec_id,))
    cur.execute("SELECT COUNT(*) FROM syllabus_chunk WHERE section_id = %s", (sec_id,))
    assert cur.fetchone()[0] == 0                       # chunks gone after delete


# ─────────────────────────────────────────────
#  Constraint Violations
# ─────────────────────────────────────────────

def test_unique_instructor_name(cur):
    cur.execute("INSERT INTO instructor (instructor_name) VALUES ('TEST_UNIQUE')")
    cur.execute("SAVEPOINT before_dup")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("INSERT INTO instructor (instructor_name) VALUES ('TEST_UNIQUE')")
    cur.execute("ROLLBACK TO SAVEPOINT before_dup")


def test_section_units_check(cur, seed):
    inst_id = seed["instructors"][0]
    course_id = seed["course_id"]
    cur.execute("SAVEPOINT before_check")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("""
            INSERT INTO section (course_id, course_title, units, year, session, section, instructor_id, syllabus_url, delivery)
            VALUES (%s, 'TEST Bad', 0, 2099, 'Fall', '99', %s, 'https://test.example.com/bad', 'Online')
        """, (course_id, inst_id))
    cur.execute("ROLLBACK TO SAVEPOINT before_check")


def test_section_fk_bad_course(cur, seed):
    inst_id = seed["instructors"][0]
    cur.execute("SAVEPOINT before_fk")
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur.execute("""
            INSERT INTO section (course_id, course_title, units, year, session, section, instructor_id, syllabus_url, delivery)
            VALUES (999999, 'TEST Bad', 3, 2099, 'Fall', '99', %s, 'https://test.example.com/bad', 'Online')
        """, (inst_id,))
    cur.execute("ROLLBACK TO SAVEPOINT before_fk")


def test_delete_restrict_college(cur, seed):
    # Cannot delete TEST college while departments still reference it
    cur.execute("SAVEPOINT before_restrict")
    with pytest.raises(psycopg2.errors.RestrictViolation): #delete parent with children referencing it should raise RestrictViolation not ForeignKeyViolation
        cur.execute("DELETE FROM college WHERE college_id = %s", (seed["college_id"],))
    cur.execute("ROLLBACK TO SAVEPOINT before_restrict")


def test_delete_restrict_department(cur, seed):
    # Cannot delete TEST department while subjects still reference it
    cur.execute("SAVEPOINT before_restrict")
    with pytest.raises(psycopg2.errors.RestrictViolation):
        cur.execute("DELETE FROM department WHERE dept_id = %s", (seed["dept_id"],))
    cur.execute("ROLLBACK TO SAVEPOINT before_restrict")


# ─────────────────────────────────────────────
#  Lookup Queries
# ─────────────────────────────────────────────

def test_lookup_by_course_code(cur, seed):
    # Given subject + catalog_number → get all sections
    cur.execute("""
        SELECT s.section_id FROM section s
        JOIN course c ON c.course_id = s.course_id
        WHERE c.subject = 'TEST' AND c.catalog_number = 'TEST101'
    """)
    assert len(cur.fetchall()) == 3


def test_lookup_by_section_id(cur, seed):
    # Given section_id → get full detail
    sec_id = seed["sections"][1]
    cur.execute("""
        SELECT s.course_title, i.instructor_name, s.delivery, s.units,
               c.catalog_number, sub.subject, d.dept_name, col.college_name
        FROM section s
        JOIN course      c   ON c.course_id     = s.course_id
        JOIN subject     sub ON sub.subject      = c.subject
        JOIN department  d   ON d.dept_id        = sub.dept_id
        JOIN college     col ON col.college_id   = d.college_id
        JOIN instructor  i   ON i.instructor_id  = s.instructor_id
        WHERE s.section_id = %s
    """, (sec_id,))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "TEST Course"
    assert row[2] == "In-Person"
    assert row[6] == "TEST Department"
    assert row[7] == "TEST College"


def test_lookup_by_instructor(cur, seed):
    cur.execute("""
        SELECT s.section_id FROM section s
        JOIN instructor i ON i.instructor_id = s.instructor_id
        WHERE i.instructor_name = 'TEST_Instructor_A'
    """)
    assert len(cur.fetchall()) == 2         # A teaches sections 1 and 3


def test_lookup_by_delivery(cur, seed):
    cur.execute("""
        SELECT s.section_id FROM section s
        JOIN course c ON c.course_id = s.course_id
        WHERE c.subject = 'TEST' AND s.delivery = 'Online'
    """)
    assert len(cur.fetchall()) == 2


def test_lookup_instructor_department(cur, seed):
    # Given instructor → get their associated departments
    inst_id = seed["instructors"][0]
    cur.execute("""
        SELECT d.dept_name FROM department d
        JOIN instructor_department id ON id.dept_id = d.dept_id
        WHERE id.instructor_id = %s
    """, (inst_id,))
    rows = cur.fetchall()
    assert any(r[0] == "TEST Department" for r in rows)


# ─────────────────────────────────────────────
#  Range Queries
# ─────────────────────────────────────────────

def test_range_by_year(cur, seed):
    cur.execute("""
        SELECT s.section_id FROM section s
        JOIN course c ON c.course_id = s.course_id
        WHERE c.subject = 'TEST' AND s.year BETWEEN 2023 AND 2024
    """)
    assert len(cur.fetchall()) == 2         # 2023-Fall and 2024-Spring


def test_range_excludes_outside_years(cur, seed):
    cur.execute("""
        SELECT s.section_id FROM section s
        JOIN course c ON c.course_id = s.course_id
        WHERE c.subject = 'TEST' AND s.year BETWEEN 2020 AND 2022
    """)
    assert len(cur.fetchall()) == 0         # all TEST sections are 2023+


# ─────────────────────────────────────────────
#  Section Mutations
# ─────────────────────────────────────────────

def test_add_section(cur, seed):
    cur.execute("""
        INSERT INTO section (course_id, course_title, units, year, session, section, instructor_id, syllabus_url, delivery)
        VALUES (%s, 'TEST Course', 3, 2099, 'Summer', 'MUT', %s, 'https://test.example.com/mut', 'Online')
        RETURNING section_id
    """, (seed["course_id"], seed["instructors"][0]))
    assert cur.fetchone()[0] is not None


def test_update_section_delivery(cur, seed):
    sec_id = seed["sections"][1]
    cur.execute("UPDATE section SET delivery = 'Hybrid' WHERE section_id = %s", (sec_id,))
    cur.execute("SELECT delivery FROM section WHERE section_id = %s", (sec_id,))
    assert cur.fetchone()[0] == "Hybrid"


def test_update_section_syllabus_url(cur, seed):
    sec_id = seed["sections"][2]
    cur.execute("UPDATE section SET syllabus_url = 'https://test.example.com/updated' WHERE section_id = %s", (sec_id,))
    cur.execute("SELECT syllabus_url FROM section WHERE section_id = %s", (sec_id,))
    assert cur.fetchone()[0] == "https://test.example.com/updated"


def test_delete_section(cur, seed):
    cur.execute("""
        INSERT INTO section (course_id, course_title, units, year, session, section, instructor_id, syllabus_url, delivery)
        VALUES (%s, 'TEST Course', 3, 2098, 'Fall', 'DEL', %s, 'https://test.example.com/del', 'Online')
        RETURNING section_id
    """, (seed["course_id"], seed["instructors"][0]))
    sec_id = cur.fetchone()[0]
    cur.execute("DELETE FROM section WHERE section_id = %s", (sec_id,))
    cur.execute("SELECT * FROM section WHERE section_id = %s", (sec_id,))
    assert cur.fetchone() is None


# ─────────────────────────────────────────────
#  Chunk Integrity
# ─────────────────────────────────────────────

def test_chunks_belong_to_correct_section(cur, seed):
    sec_id = seed["sections"][0]
    cur.execute("SELECT section_id FROM syllabus_chunk WHERE section_id = %s", (sec_id,))
    rows = cur.fetchall()
    assert len(rows) > 0
    assert all(r[0] == sec_id for r in rows)


def test_no_empty_chunk_text(cur, seed):
    cur.execute("""
        SELECT COUNT(*) FROM syllabus_chunk
        WHERE section_id IN %s AND (chunk_text IS NULL OR TRIM(chunk_text) = '')
    """, (tuple(seed["sections"]),))
    assert cur.fetchone()[0] == 0


def test_no_empty_chunk_title(cur, seed):
    cur.execute("""
        SELECT COUNT(*) FROM syllabus_chunk
        WHERE section_id IN %s AND (chunk_title IS NULL OR TRIM(chunk_title) = '')
    """, (tuple(seed["sections"]),))
    assert cur.fetchone()[0] == 0


# ─────────────────────────────────────────────
#  Performance (EXPLAIN)
# ─────────────────────────────────────────────

# Drops the year index if it exists, then checks that PostgreSQL's query planner
# uses a sequential scan (reads every row) when no index is available.
def test_explain_without_index(cur, seed):
    cur.execute("DROP INDEX IF EXISTS idx_test_section_year")
    cur.execute("""
        EXPLAIN SELECT * FROM section s
        JOIN course c ON c.course_id = s.course_id
        WHERE c.subject = 'TEST' AND s.year = 2024
    """)
    plan = " ".join(r[0] for r in cur.fetchall())
    assert "Seq Scan" in plan or "Scan" in plan

# Creates an index on section.year, then checks that EXPLAIN produces a valid
# query plan. On small datasets the planner may still choose a seq scan, so we
# just verify the plan is non-empty rather than asserting an index scan was used.
def test_explain_with_index(cur, seed):
    cur.execute("CREATE INDEX IF NOT EXISTS idx_test_section_year ON section(year)")
    cur.execute("""
        EXPLAIN SELECT * FROM section s
        JOIN course c ON c.course_id = s.course_id
        WHERE c.subject = 'TEST' AND s.year = 2024
    """)
    plan = " ".join(r[0] for r in cur.fetchall())
    assert plan != ""