"""
Comprehensive DB Validation Test Suite for Course Advisor
Run: pytest tests/course_advisor_test_db_validation.py -v -s

Demo order:
  Phase 1 – Connection & Schema
  Phase 2 – Count Validations       (broad → narrow: college → chunk)
  Phase 3 – Set Comparisons         (exact value matching vs CSV)
  Phase 4 – Unique Constraints      (no duplicate rows)
  Phase 5 – Referential Integrity   (no orphaned records)
  Phase 6 – Data Quality            (nulls, ranges, allowed values)
  Phase 7 – Embedding Quality       (Dimension consistency, no nulls, chunks per section distribution)
  Phase 8 – Grand Finale            (full DB ↔ CSV comparison)
"""

import os
import pandas as pd
import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# DB Connection Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def conn():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
    )


@pytest.fixture(scope="session")
def cur(conn):
    c = conn.cursor()
    yield c
    c.close()


# ─────────────────────────────────────────────
# CSV Fixture – loaded once, reused across tests
# ─────────────────────────────────────────────


@pytest.fixture(scope="session")
def df():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "../scripts/chunks_with_embeddings.csv")
    data = pd.read_csv(path)
    data["section"] = data["section"].astype(str)
    return data


# ─────────────────────────────────────────────
# DB Query Helpers
# ─────────────────────────────────────────────

def fetch_db_df(cur):
    cur.execute("""
        SELECT
            s.subject,
            c.catalog_number,
            sec.course_title,
            sec.units,
            i.instructor_name,
            sec.year,
            sec.session,
            sec.section,
            sec.syllabus_url,
            sec.delivery,
            d.dept_name,
            s.subject_name,
            col.college_name,
            COUNT(sc.chunk_id) AS chunk_count
        FROM section sec
        JOIN course c         ON sec.course_id     = c.course_id
        JOIN subject s        ON c.subject         = s.subject
        JOIN department d     ON s.dept_id         = d.dept_id
        JOIN college col      ON d.college_id      = col.college_id
        JOIN instructor i     ON sec.instructor_id = i.instructor_id
        LEFT JOIN syllabus_chunk sc ON sc.section_id = sec.section_id
        GROUP BY
            s.subject, c.catalog_number, sec.course_title, sec.units,
            i.instructor_name, sec.year, sec.session, sec.section,
            sec.syllabus_url, sec.delivery,
            d.dept_name, s.subject_name, col.college_name
        ORDER BY s.subject, c.catalog_number, sec.year, sec.session, sec.section
    """)
    cols = [
        "subject", "catalog_number", "course_title", "units", "instructor_name",
        "year", "session", "section", "syllabus_url", "delivery",
        "dept_name", "subject_name", "college_name", "chunk_count"
    ]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def build_expected_df(df: pd.DataFrame):
    section_keys = ["subject", "catalog_number", "year", "session", "section"]
    csv_chunks = (
        df.groupby(section_keys)
          .size()
          .reset_index(name="chunk_count")
    )
    csv_sections = (
        df[section_keys + [
            "course_title", "units", "instructor_name",
            "syllabus_url", "delivery", "dept_name",
            "subject_name", "college_name"
        ]]
        .drop_duplicates(subset=section_keys)
        .merge(csv_chunks, on=section_keys)
    )
    csv_sections["section"]        = csv_sections["section"].astype(str)
    csv_sections["catalog_number"] = csv_sections["catalog_number"].astype(str)
    csv_sections["year"]           = csv_sections["year"].astype(int)
    csv_sections["units"]          = csv_sections["units"].astype(float)
    csv_sections["chunk_count"]    = csv_sections["chunk_count"].astype(int)
    return csv_sections


# ═══════════════════════════════════════════════════════════
# PHASE 1 – Connection & Schema
# ═══════════════════════════════════════════════════════════

def test_db_connection(conn):
    """Verify the database is reachable before running any other test."""
    print("\n--- DB CONNECTION CHECK ---")

    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()[0]

    print(f"Connection response: {result}")

    assert result == 1, "Database did not respond to SELECT 1"

    print("✅ Database connection is healthy!\n")


def test_tables_exist(cur):
    """All expected tables must be present in the public schema."""
    print("\n--- SCHEMA / TABLE EXISTENCE CHECK ---")

    expected_tables = {
        "college", "department", "subject", "course",
        "instructor", "section", "syllabus_chunk"
    }

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
    """)
    existing_tables = {row[0] for row in cur.fetchall()}

    missing = expected_tables - existing_tables

    for t in sorted(expected_tables):
        status = "✅" if t in existing_tables else "❌ MISSING"
        print(f"  {status}  {t}")

    assert not missing, f"Missing tables: {sorted(missing)}"

    print("✅ All expected tables exist!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 2 – Count Validations  (broad → narrow)
# ═══════════════════════════════════════════════════════════

def test_college_count(cur, df):
    print("\n--- COLLEGE COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM college")
    db_count = cur.fetchone()[0]
    csv_count = df["college_name"].nunique()

    print(f"DB unique colleges : {db_count}")
    print(f"CSV unique colleges: {csv_count}")

    assert db_count == csv_count, (
        f"College count mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ College counts match!\n")


def test_department_count(cur, df):
    print("\n--- DEPARTMENT COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM department")
    db_count = cur.fetchone()[0]
    csv_count = df["dept_name"].nunique()

    print(f"DB unique departments : {db_count}")
    print(f"CSV unique departments: {csv_count}")

    assert db_count == csv_count, (
        f"Department count mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ Department counts match!\n")


def test_subject_count(cur, df):
    print("\n--- SUBJECT COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM subject")
    db_count = cur.fetchone()[0]
    csv_count = df["subject"].nunique()

    print(f"DB unique subjects : {db_count}")
    print(f"CSV unique subjects: {csv_count}")

    assert db_count == csv_count, (
        f"Subject count mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ Subject counts match!\n")


def test_course_count(cur, df):
    print("\n--- COURSE COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM course")
    db_count = cur.fetchone()[0]
    csv_count = df[["subject", "catalog_number"]].drop_duplicates().shape[0]

    print(f"DB unique courses : {db_count}")
    print(f"CSV unique courses: {csv_count}")

    assert db_count == csv_count, (
        f"Course count mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ Course counts match!\n")


def test_instructor_count(cur, df):
    print("\n--- INSTRUCTOR COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(DISTINCT instructor_name) FROM instructor")
    db_count = cur.fetchone()[0]
    csv_count = df["instructor_name"].nunique()

    print(f"DB unique instructors : {db_count}")
    print(f"CSV unique instructors: {csv_count}")

    assert db_count == csv_count, (
        f"Instructor count mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ Instructor counts match!\n")


def test_section_count(cur, df):
    print("\n--- SECTION COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM section")
    db_count = cur.fetchone()[0]

    section_keys = ["subject", "catalog_number", "year", "session", "section"]
    csv_count = df.drop_duplicates(subset=section_keys).shape[0]

    print(f"DB section count : {db_count}")
    print(f"CSV section count: {csv_count}")

    assert db_count == csv_count, (
        f"Section count mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ Section counts match!\n")


def test_total_chunk_count(cur, df):
    print("\n--- CHUNK COUNT VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM syllabus_chunk")
    db_count = cur.fetchone()[0]
    csv_count = len(df)

    print(f"DB chunk count : {db_count}")
    print(f"CSV chunk count: {csv_count}")

    assert db_count == csv_count, (
        f"Chunk mismatch: DB={db_count}, CSV={csv_count}"
    )
    print("✅ Chunk counts match!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 3 – Set Comparisons
# ═══════════════════════════════════════════════════════════

def test_subjects_match_csv(cur, df):
    """The set of subject codes in the DB must exactly match the CSV."""
    print("\n--- SUBJECT CODE SET COMPARISON ---")

    cur.execute("SELECT DISTINCT subject FROM subject ORDER BY subject")
    db_subjects  = {row[0] for row in cur.fetchall()}
    csv_subjects = set(df["subject"].unique())

    only_in_db  = db_subjects  - csv_subjects
    only_in_csv = csv_subjects - db_subjects

    if only_in_db:
        print(f"  In DB only  : {sorted(only_in_db)}")
    if only_in_csv:
        print(f"  In CSV only : {sorted(only_in_csv)}")

    print(f"DB subjects  : {len(db_subjects)}")
    print(f"CSV subjects : {len(csv_subjects)}")

    assert only_in_db  == set(), f"Subjects in DB but not CSV: {only_in_db}"
    assert only_in_csv == set(), f"Subjects in CSV but not DB: {only_in_csv}"

    print("✅ Subject code sets match!\n")


def test_instructors_match_csv(cur, df):
    """The set of instructor names in the DB must exactly match the CSV."""
    print("\n--- INSTRUCTOR NAME SET COMPARISON ---")

    cur.execute("SELECT DISTINCT instructor_name FROM instructor ORDER BY instructor_name")
    db_instructors  = {row[0] for row in cur.fetchall()}
    csv_instructors = set(df["instructor_name"].unique())

    only_in_db  = db_instructors  - csv_instructors
    only_in_csv = csv_instructors - db_instructors

    if only_in_db:
        print(f"  In DB only  : {sorted(only_in_db)}")
    if only_in_csv:
        print(f"  In CSV only : {sorted(only_in_csv)}")

    print(f"DB instructors  : {len(db_instructors)}")
    print(f"CSV instructors : {len(csv_instructors)}")

    assert only_in_db  == set(), f"Instructors in DB but not CSV: {only_in_db}"
    assert only_in_csv == set(), f"Instructors in CSV but not DB: {only_in_csv}"

    print("✅ Instructor name sets match!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 4 – Unique Constraints
# ═══════════════════════════════════════════════════════════

def test_no_duplicate_subjects(cur):
    """Subject codes should be unique."""
    print("\n--- DUPLICATE SUBJECT CHECK ---")

    cur.execute("""
        SELECT subject, COUNT(*) AS cnt
        FROM subject
        GROUP BY subject
        HAVING COUNT(*) > 1
    """)
    dupes = cur.fetchall()

    for row in dupes:
        print(f"  DUPLICATE: subject='{row[0]}', count={row[1]}")

    assert len(dupes) == 0, f"{len(dupes)} duplicate subject code(s) found"

    print("✅ No duplicate subjects!\n")


def test_no_duplicate_instructors(cur):
    """Instructor names should be unique (no accidental double inserts)."""
    print("\n--- DUPLICATE INSTRUCTOR CHECK ---")

    cur.execute("""
        SELECT instructor_name, COUNT(*) AS cnt
        FROM instructor
        GROUP BY instructor_name
        HAVING COUNT(*) > 1
    """)
    dupes = cur.fetchall()

    for row in dupes:
        print(f"  DUPLICATE: instructor_name='{row[0]}', count={row[1]}")

    assert len(dupes) == 0, f"{len(dupes)} duplicate instructor name(s) found"

    print("✅ No duplicate instructors!\n")


def test_no_duplicate_sections(cur):
    """No two rows in the section table should share the same
    (course_id, year, session, section) composite key."""
    print("\n--- DUPLICATE SECTION CHECK ---")

    cur.execute("""
        SELECT course_id, year, session, section, COUNT(*) AS cnt
        FROM section
        GROUP BY course_id, year, session, section
        HAVING COUNT(*) > 1
    """)
    dupes = cur.fetchall()

    for row in dupes:
        print(f"  DUPLICATE: course_id={row[0]}, year={row[1]}, "
              f"session={row[2]}, section={row[3]}, count={row[4]}")

    assert len(dupes) == 0, f"{len(dupes)} duplicate section key(s) found"

    print("✅ No duplicate sections!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 5 – Referential Integrity
# ═══════════════════════════════════════════════════════════

def test_no_orphaned_subjects(cur):
    """Every subject must belong to a valid department."""
    print("\n--- ORPHANED SUBJECT CHECK ---")

    cur.execute("""
        SELECT COUNT(*) FROM subject s
        LEFT JOIN department d ON s.dept_id = d.dept_id
        WHERE d.dept_id IS NULL
    """)
    orphaned = cur.fetchone()[0]

    print(f"Subjects missing department: {orphaned}")

    assert orphaned == 0, f"{orphaned} subject(s) have no matching department"

    print("✅ No orphaned subjects!\n")


def test_no_orphaned_sections(cur):
    """Every section must have a valid course and instructor."""
    print("\n--- ORPHANED SECTION CHECK ---")

    cur.execute("""
        SELECT COUNT(*) FROM section sec
        LEFT JOIN course c ON sec.course_id = c.course_id
        WHERE c.course_id IS NULL
    """)
    orphaned_course = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM section sec
        LEFT JOIN instructor i ON sec.instructor_id = i.instructor_id
        WHERE i.instructor_id IS NULL
    """)
    orphaned_instructor = cur.fetchone()[0]

    print(f"Sections missing course     : {orphaned_course}")
    print(f"Sections missing instructor : {orphaned_instructor}")

    assert orphaned_course     == 0, f"{orphaned_course} section(s) have no matching course"
    assert orphaned_instructor == 0, f"{orphaned_instructor} section(s) have no matching instructor"

    print("✅ No orphaned sections!\n")


def test_no_orphaned_chunks(cur):
    """Every syllabus chunk must reference a valid section."""
    print("\n--- ORPHANED CHUNK CHECK ---")

    cur.execute("""
        SELECT COUNT(*) FROM syllabus_chunk sc
        LEFT JOIN section sec ON sc.section_id = sec.section_id
        WHERE sec.section_id IS NULL
    """)
    orphaned = cur.fetchone()[0]

    print(f"Chunks missing section: {orphaned}")

    assert orphaned == 0, f"{orphaned} chunk(s) have no matching section"

    print("✅ No orphaned chunks!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 6 – Data Quality
# ═══════════════════════════════════════════════════════════

def test_no_null_course_titles(cur):
    print("\n--- NULL COURSE TITLE CHECK ---")

    cur.execute("SELECT COUNT(*) FROM section WHERE course_title IS NULL OR course_title = ''")
    null_count = cur.fetchone()[0]

    print(f"Sections with null/empty course_title: {null_count}")

    assert null_count == 0, f"{null_count} section(s) have null or empty course_title"

    print("✅ All sections have a course title!\n")


def test_no_null_instructor_names(cur):
    print("\n--- NULL INSTRUCTOR NAME CHECK ---")

    cur.execute("SELECT COUNT(*) FROM instructor WHERE instructor_name IS NULL OR instructor_name = ''")
    null_count = cur.fetchone()[0]

    print(f"Instructors with null/empty name: {null_count}")

    assert null_count == 0, f"{null_count} instructor(s) have null or empty name"

    print("✅ All instructors have a name!\n")


def test_units_are_positive(cur):
    print("\n--- UNITS VALIDATION ---")

    cur.execute("SELECT COUNT(*) FROM section WHERE units IS NOT NULL AND units <= 0")
    bad_count = cur.fetchone()[0]

    print(f"Sections with non-positive units: {bad_count}")

    assert bad_count == 0, f"{bad_count} section(s) have zero or negative units"

    print("✅ All unit values are positive!\n")


def test_year_is_reasonable(cur):
    """Years should be within a sensible range (e.g. 2000–2100)."""
    print("\n--- YEAR RANGE VALIDATION ---")

    cur.execute("SELECT MIN(year), MAX(year) FROM section")
    min_year, max_year = cur.fetchone()

    print(f"Year range in DB: {min_year} – {max_year}")

    assert min_year >= 2000, f"Suspiciously old year found: {min_year}"
    assert max_year <= 2100, f"Suspiciously far future year found: {max_year}"

    print("✅ All years are within expected range!\n")


def test_delivery_values_valid(cur):
    """The delivery field should only contain known/expected values."""
    print("\n--- DELIVERY VALUE VALIDATION ---")

    # Adjust this set to match your actual allowed delivery modes
    ALLOWED_DELIVERY = {"In Person", "Online", "Hybrid", "Fully Online"}

    cur.execute("SELECT DISTINCT delivery FROM section WHERE delivery IS NOT NULL")
    db_values = {row[0] for row in cur.fetchall()}

    unexpected = db_values - ALLOWED_DELIVERY

    print(f"Delivery values in DB : {sorted(db_values)}")
    if unexpected:
        print(f"Unexpected values      : {sorted(unexpected)}")

    assert not unexpected, (
        f"Unexpected delivery value(s): {sorted(unexpected)}. "
        f"Update ALLOWED_DELIVERY if these are intentional."
    )

    print("✅ All delivery values are valid!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 7 – Embedding Quality
# ═══════════════════════════════════════════════════════════

def test_no_null_embeddings(cur):
    """Every chunk should have an embedding stored."""
    print("\n--- NULL EMBEDDING CHECK ---")

    cur.execute("SELECT COUNT(*) FROM syllabus_chunk WHERE embedding IS NULL")
    null_count = cur.fetchone()[0]

    print(f"Chunks missing embedding: {null_count}")

    assert null_count == 0, f"{null_count} chunk(s) are missing embeddings"

    print("✅ All chunks have embeddings!\n")


def test_embedding_dimensions_consistent(cur):
    """All embeddings must share the same vector dimensionality.
    Uses pgvector's vector_dims() function."""
    print("\n--- EMBEDDING DIMENSION CONSISTENCY CHECK ---")

    cur.execute("""
        SELECT
            MIN(vector_dims(embedding)) AS min_dim,
            MAX(vector_dims(embedding)) AS max_dim,
            COUNT(*)                    AS total_chunks
        FROM syllabus_chunk
        WHERE embedding IS NOT NULL
    """)
    min_dim, max_dim, total = cur.fetchone()

    print(f"Total chunks with embedding : {total}")
    print(f"Min embedding dimension     : {min_dim}")
    print(f"Max embedding dimension     : {max_dim}")

    assert min_dim == max_dim, (
        f"Inconsistent embedding dimensions found: min={min_dim}, max={max_dim}"
    )
    assert min_dim is not None, "No embeddings found — cannot verify dimensions"

    print(f"✅ All embeddings have consistent dimension ({min_dim}D)!\n")


def test_chunks_per_section_distribution(cur):
    """Print a distribution of chunks per section; flag any section with 0 chunks."""
    print("\n--- CHUNKS PER SECTION DISTRIBUTION ---")

    cur.execute("""
        SELECT
            MIN(chunk_count)                              AS min_chunks,
            MAX(chunk_count)                              AS max_chunks,
            ROUND(AVG(chunk_count), 2)                    AS avg_chunks,
            COUNT(*) FILTER (WHERE chunk_count = 0)       AS sections_with_zero_chunks
        FROM (
            SELECT sec.section_id, COUNT(sc.chunk_id) AS chunk_count
            FROM section sec
            LEFT JOIN syllabus_chunk sc ON sc.section_id = sec.section_id
            GROUP BY sec.section_id
        ) counts
    """)
    min_c, max_c, avg_c, zero_sections = cur.fetchone()

    print(f"Min chunks per section : {min_c}")
    print(f"Max chunks per section : {max_c}")
    print(f"Avg chunks per section : {avg_c}")
    print(f"Sections with 0 chunks : {zero_sections}")

    assert zero_sections == 0, (
        f"{zero_sections} section(s) have no chunks — possible ingestion failure"
    )

    print("✅ All sections have at least one chunk!\n")


# ═══════════════════════════════════════════════════════════
# PHASE 8 – Grand Finale: Full DB ↔ CSV Comparison
# ═══════════════════════════════════════════════════════════

def test_database_matches_csv(cur, df):
    """Row-by-row, column-by-column verification that the DB matches the source CSV."""
    print("\n================ DATABASE VALIDATION START ================\n")

    print("Fetching data from database...")
    db_df = fetch_db_df(cur)
    print(f"DB rows fetched: {len(db_df)}")

    print("\nBuilding expected CSV dataframe...")
    csv_df = build_expected_df(df)
    print(f"CSV expected rows: {len(csv_df)}")

    sort_cols = ["subject", "catalog_number", "year", "session", "section"]
    db_df  = db_df.sort_values(sort_cols).reset_index(drop=True)
    csv_df = csv_df.sort_values(sort_cols).reset_index(drop=True)

    print("\nComparing shapes...")
    print(f"DB shape : {db_df.shape}")
    print(f"CSV shape: {csv_df.shape}")

    assert len(db_df) == len(csv_df), (
        f"Row mismatch: DB={len(db_df)} CSV={len(csv_df)}"
    )

    print("\nRunning full dataframe comparison...")

    try:
        pd.testing.assert_frame_equal(
            db_df,
            csv_df,
            check_dtype=False,
            check_like=True,
        )
        print("\n✅ SUCCESS: Database matches CSV exactly!")
    except AssertionError as e:
        print("\n❌ MISMATCH FOUND")
        print(str(e))
        raise

    print("\n================ VALIDATION COMPLETE ================\n")
