import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV      = os.path.join(BASE_DIR, "chunks_with_embeddings.csv")
INDEX_SQL_FILE = os.path.join(BASE_DIR, "course_advisor_db_indexing.sql")

# ─────────────────────────────────────────────
#  Connection
# ─────────────────────────────────────────────
def get_connection(dbname):
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
        dbname=dbname,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


# ─────────────────────────────────────────────
#  Load & Clean
# ─────────────────────────────────────────────
def load_and_clean(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    print(f"Loaded {len(df)} rows from {filepath}")

    return df


# ─────────────────────────────────────────────
#  Insert Functions
# ─────────────────────────────────────────────
def insert_colleges(cur, df: pd.DataFrame):
    colleges = df[["college_name"]].drop_duplicates()
    execute_values(cur, """
        INSERT INTO college (college_name)
        VALUES %s
        ON CONFLICT (college_name) DO NOTHING
    """, [tuple(r) for r in colleges.itertuples(index=False)])
    print(f"Inserted {len(colleges)} colleges")


def insert_departments(cur, df: pd.DataFrame) -> dict:
    cur.execute("SELECT college_name, college_id FROM college")
    college_map = {name: cid for name, cid in cur.fetchall()}

    depts = df[["dept_name", "college_name"]].drop_duplicates()
    execute_values(cur, """
        INSERT INTO department (dept_name, college_id)
        VALUES %s
        ON CONFLICT (dept_name) DO NOTHING
    """, [(row.dept_name, college_map[row.college_name]) for row in depts.itertuples(index=False)])

    cur.execute("SELECT dept_name, dept_id FROM department")
    dept_map = {name: did for name, did in cur.fetchall()}
    print(f"Inserted {len(depts)} departments")
    return dept_map


def insert_subjects(cur, df: pd.DataFrame, dept_map: dict):
    subjects = df[["subject", "subject_name", "dept_name"]].drop_duplicates()
    execute_values(cur, """
        INSERT INTO subject (subject, subject_name, dept_id)
        VALUES %s
        ON CONFLICT (subject) DO NOTHING
    """, [(row.subject, row.subject_name, dept_map[row.dept_name]) for row in subjects.itertuples(index=False)])
    print(f"Inserted {len(subjects)} subjects")


def insert_courses(cur, df: pd.DataFrame):
    courses = df[["subject", "catalog_number"]].drop_duplicates(
        subset=["subject", "catalog_number"]
    )
    execute_values(cur, """
        INSERT INTO course (subject, catalog_number)
        VALUES %s
        ON CONFLICT (subject, catalog_number) DO NOTHING
    """, [tuple(r) for r in courses.itertuples(index=False)])
    print(f"Inserted {len(courses)} courses")


def insert_instructors(cur, df: pd.DataFrame) -> dict:
    instructors = df[["instructor_name"]].drop_duplicates()
    execute_values(cur, """
        INSERT INTO instructor (instructor_name)
        VALUES %s
        ON CONFLICT (instructor_name) DO NOTHING
    """, [tuple(r) for r in instructors.itertuples(index=False)])

    cur.execute("SELECT instructor_name, instructor_id FROM instructor")
    instructor_map = {name: iid for name, iid in cur.fetchall()}
    print(f"Inserted {len(instructors)} instructors")
    return instructor_map


def insert_instructor_departments(cur, df: pd.DataFrame, instructor_map: dict, dept_map: dict):
    instructor_depts = df[["instructor_name", "dept_name"]].drop_duplicates()
    execute_values(cur, """
        INSERT INTO instructor_department (instructor_id, dept_id)
        VALUES %s
        ON CONFLICT (instructor_id, dept_id) DO NOTHING
    """, [
        (instructor_map[row.instructor_name], dept_map[row.dept_name])
        for row in instructor_depts.itertuples(index=False)
    ])
    print(f"Inserted {len(instructor_depts)} instructor-department mappings")


def insert_sections(cur, df: pd.DataFrame, instructor_map: dict) -> dict:
    cur.execute("SELECT subject, catalog_number, course_id FROM course")
    course_map = {(subj, cat): cid for subj, cat, cid in cur.fetchall()}

    section_cols = ["subject", "catalog_number", "course_title", "units",
                    "year", "session", "section", "instructor_name",
                    "syllabus_url", "delivery"]
    sections = df[section_cols].drop_duplicates(
        subset=["subject", "catalog_number", "year", "session", "section"]
    )

    execute_values(cur, """
        INSERT INTO section
            (course_id, course_title, units, year, session, section,
             instructor_id, syllabus_url, delivery)
        VALUES %s
        ON CONFLICT (course_id, year, session, section) DO NOTHING
    """, [
        (
            course_map[(row.subject, row.catalog_number)],
            row.course_title,
            row.units,
            row.year,
            row.session,
            row.section,
            instructor_map[row.instructor_name],
            row.syllabus_url,
            row.delivery,
        )
        for row in sections.itertuples(index=False)
    ])
    print(f"Inserted {len(sections)} sections")

    cur.execute("SELECT course_id, year, session, section, section_id FROM section")
    section_map = {
        (cid, yr, sess, sec): sid
        for cid, yr, sess, sec, sid in cur.fetchall()
    }
    return section_map


def insert_syllabus_chunks(cur, df: pd.DataFrame, section_map: dict):
    cur.execute("SELECT subject, catalog_number, course_id FROM course")
    course_map = {(subj, cat): cid for subj, cat, cid in cur.fetchall()}

    rows = []
    for row in df.itertuples(index=False):
        course_id  = course_map[(row.subject, row.catalog_number)]
        section_id = section_map[(course_id, row.year, row.session, str(row.section))]
        rows.append((section_id, row.chunk_title, row.chunk_text, row.embedding))

    execute_values(cur, """
        INSERT INTO syllabus_chunk (section_id, chunk_title, chunk_text, embedding)
        VALUES %s
    """, rows, template="(%s, %s, %s, %s::vector)", page_size=1000)
    print(f"Inserted {len(rows)} syllabus chunks")


# ─────────────────────────────────────────────
#  Indexing Logic (Using external SQL file)
# ─────────────────────────────────────────────
def apply_indexes(cur):
    if not os.path.exists(INDEX_SQL_FILE):
        print(f"Warning: Indexing file {INDEX_SQL_FILE} not found. Skipping indexing.")
        return

    print(f"\nApplying indexes from {os.path.basename(INDEX_SQL_FILE)}...")
    # Increase maintenance memory for heavy HNSW index building
    cur.execute("SET maintenance_work_mem = '256MB';")
    
    with open(INDEX_SQL_FILE, 'r') as f:
        sql_commands = f.read()
        if sql_commands.strip():
            cur.execute(sql_commands)
            print("Successfully applied indexes from SQL file.")


# ─────────────────────────────────────────────
#  Validate
# ─────────────────────────────────────────────
def validate(cur, df: pd.DataFrame):
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
            sec.syllabus_url, sec.delivery, d.dept_name, s.subject_name, col.college_name
        ORDER BY s.subject, c.catalog_number, sec.year, sec.session, sec.section
    """)

    cols = ["subject", "catalog_number", "course_title", "units", "instructor_name",
            "year", "session", "section", "syllabus_url", "delivery",
            "dept_name", "subject_name", "college_name", "chunk_count"]
    db_df = pd.DataFrame(cur.fetchall(), columns=cols)

    section_keys = ["subject", "catalog_number", "year", "session", "section"]
    csv_chunks = df.groupby(section_keys).size().reset_index(name="chunk_count")
    csv_sections = (
        df[section_keys + ["course_title", "units", "instructor_name",
                           "syllabus_url", "delivery", "dept_name",
                           "subject_name", "college_name"]]
        .drop_duplicates(subset=section_keys)
        .merge(csv_chunks, on=section_keys)
    )

    for frame in [csv_sections, db_df]:
        frame["section"]        = frame["section"].astype(str)
        frame["catalog_number"] = frame["catalog_number"].astype(str)
        frame["year"]           = frame["year"].astype(int)
        frame["units"]          = frame["units"].astype(float)
        frame["chunk_count"]    = frame["chunk_count"].astype(int)

    print(f"Unique sections in CSV : {len(csv_sections)}")
    print(f"Sections in DB         : {len(db_df)}")

    cur.execute("SELECT COUNT(*) FROM syllabus_chunk")
    total_db_chunks = cur.fetchone()[0]
    print(f"Total chunks in DB     : {total_db_chunks}")
    print(f"Total chunks in CSV    : {len(df)}")

    merge_cols = section_keys + ["chunk_count"]
    missing = (
        csv_sections[merge_cols]
        .merge(db_df[merge_cols], on=merge_cols, how="left", indicator=True)
        .query('_merge == "left_only"')
    )
    if len(missing) > 0:
        print(f"\n{len(missing)} sections with mismatched chunk counts:")
        print(missing)
    else:
        print("\nAll sections and chunk counts match!")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main(dbname, apply_idx=True):
    print(f"\n--- Loading Database: {dbname} (Apply Indexes: {apply_idx}) ---")
    df = load_and_clean(INPUT_CSV)
    df["section"] = df["section"].astype(str)

    conn = get_connection(dbname)
    cur = conn.cursor()

    try:
        insert_colleges(cur, df)
        conn.commit()

        dept_map = insert_departments(cur, df)
        conn.commit()

        insert_subjects(cur, df, dept_map)
        conn.commit()

        insert_courses(cur, df)
        conn.commit()

        instructor_map = insert_instructors(cur, df)
        conn.commit()

        insert_instructor_departments(cur, df, instructor_map, dept_map)
        conn.commit()

        section_map = insert_sections(cur, df, instructor_map)
        conn.commit()

        insert_syllabus_chunks(cur, df, section_map)
        conn.commit()

        if apply_idx:
            apply_indexes(cur)
            conn.commit()
        else:
            print("Skipping indexing for this database.")

        print("\nValidating...")
        validate(cur, df)
        print(f"\nFinished loading {dbname} successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    # Load production database with indexes
    main("course_advisor", apply_idx=True)
    
    # Load test database without indexes
    main("course_advisor_test", apply_idx=False)
