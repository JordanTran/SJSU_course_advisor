"""
test_db.py – Course Advisor DB Test Suite
Run: pytest tests/course_advisor_test_db_validation.py -v -s
Requires: pip install psycopg2-binary python-dotenv
"""
import os
import pandas as pd
import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# DB Connection Fixture
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
# Load CSV once, will compare to DB
# ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def df():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "../scripts/chunks_with_embeddings.csv")

    data = pd.read_csv(path)
    data["section"] = data["section"].astype(str)
    return data


# ─────────────────────────────────────────────
# DB Query Builder, Helper for test
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


# ─────────────────────────────────────────────
# CSV Expected Builder, helper
# ─────────────────────────────────────────────

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

    # normalize types (important for comparisons)
    csv_sections["section"] = csv_sections["section"].astype(str)
    csv_sections["catalog_number"] = csv_sections["catalog_number"].astype(str)
    csv_sections["year"] = csv_sections["year"].astype(int)
    csv_sections["units"] = csv_sections["units"].astype(float)
    csv_sections["chunk_count"] = csv_sections["chunk_count"].astype(int)

    return csv_sections


# ─────────────────────────────────────────────
# MAIN TEST
# ─────────────────────────────────────────────

# def test_database_matches_csv(cur, df):
#     db_df = fetch_db_df(cur)
#     csv_df = build_expected_df(df)

#     # sort so ordering doesn't break equality
#     sort_cols = ["subject", "catalog_number", "year", "session", "section"]

#     db_df = db_df.sort_values(sort_cols).reset_index(drop=True)
#     csv_df = csv_df.sort_values(sort_cols).reset_index(drop=True)

#     # ─────────────────────────────
#     # 1. Shape check
#     # ─────────────────────────────
#     assert len(db_df) == len(csv_df), (
#         f"Row mismatch: DB={len(db_df)} CSV={len(csv_df)}"
#     )

#     # ─────────────────────────────
#     # 2. Exact data match
#     # ─────────────────────────────
#     pd.testing.assert_frame_equal(
#         db_df,
#         csv_df,
#         check_dtype=False,
#         check_like=True
#     )
def test_database_matches_csv(cur, df):
    print("\n================ DATABASE VALIDATION START ================\n")

    print("Fetching data from database...")
    db_df = fetch_db_df(cur)
    print(f"DB rows fetched: {len(db_df)}")

    print("\nBuilding expected CSV dataframe...")
    csv_df = build_expected_df(df)
    print(f"CSV expected rows: {len(csv_df)}")

    sort_cols = ["subject", "catalog_number", "year", "session", "section"]

    db_df = db_df.sort_values(sort_cols).reset_index(drop=True)
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
            check_like=True
        )
        print("\n✅ SUCCESS: Database matches CSV exactly!")
    except AssertionError as e:
        print("\n❌ MISMATCH FOUND")
        print(str(e))
        raise

    print("\n================ VALIDATION COMPLETE ================\n")


# ─────────────────────────────────────────────
# Extra sanity test: chunk counts match
# ─────────────────────────────────────────────

# def test_total_chunk_count(cur, df):
#     cur.execute("SELECT COUNT(*) FROM syllabus_chunk")
#     db_count = cur.fetchone()[0]

#     csv_count = len(df)

#     assert db_count == csv_count, (
#         f"Chunk mismatch: DB={db_count}, CSV={csv_count}"
#     )
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