import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     os.getenv("DB_PORT", 5432),
    "dbname":   os.getenv("DB_NAME", "your_db"),
    "user":     os.getenv("DB_USER", "your_user"),
    "password": os.getenv("DB_PASSWORD", "your_password"),
}


# ─────────────────────────────────────────────
#  Connection
# ─────────────────────────────────────────────
def get_connection():
    return psycopg2.connect(**DB_CONFIG)


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
    courses = df[["subject", "catalog_number", "course_title", "units"]].drop_duplicates(
        subset=["subject", "catalog_number"]
    )
    execute_values(cur, """
        INSERT INTO course (subject, catalog_number, course_title, units)
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


def insert_sections(cur, df: pd.DataFrame, instructor_map: dict):
    cur.execute("SELECT subject, catalog_number, course_id FROM course")
    course_map = {(subj, cat): cid for subj, cat, cid in cur.fetchall()}

    sections = df[["subject", "catalog_number", "year", "session", "section", "instructor_name", "syllabus_url"]]
    execute_values(cur, """
        INSERT INTO section (course_id, year, session, section, instructor_id, syllabus_url)
        VALUES %s
        ON CONFLICT (course_id, year, session, section) DO NOTHING
    """, [
        (
            course_map[(row.subject, row.catalog_number)],
            row.year,
            row.session,
            row.section,
            instructor_map[row.instructor_name],
            row.syllabus_url
        )
        for row in sections.itertuples(index=False)
    ])
    print(f"Inserted {len(sections)} sections")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    filepath = "cmpe_syllabi_db.csv"

    df = load_and_clean(filepath)

    conn = get_connection()
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

        insert_sections(cur, df, instructor_map)
        conn.commit()

        print("All data inserted successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()