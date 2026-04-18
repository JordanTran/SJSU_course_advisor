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


def insert_sections(cur, df: pd.DataFrame, instructor_map: dict):
    cur.execute("SELECT subject, catalog_number, course_id FROM course")
    course_map = {(subj, cat): cid for subj, cat, cid in cur.fetchall()}

    sections = df[["subject", "catalog_number", "course_title", "units",
                   "year", "session", "section", "instructor_name", "syllabus_url"]]
    execute_values(cur, """
        INSERT INTO section (course_id, course_title, units, year, session, section, instructor_id, syllabus_url)
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
            row.syllabus_url
        )
        for row in sections.itertuples(index=False)
    ])
    print(f"Inserted {len(sections)} sections")


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
            d.dept_name,
            s.subject_name,
            col.college_name
        FROM section sec
        JOIN course c         ON sec.course_id     = c.course_id
        JOIN subject s        ON c.subject         = s.subject
        JOIN department d     ON s.dept_id         = d.dept_id
        JOIN college col      ON d.college_id      = col.college_id
        JOIN instructor i     ON sec.instructor_id = i.instructor_id
        ORDER BY s.subject, c.catalog_number, sec.year, sec.session, sec.section
    """)

    cols = ["subject", "catalog_number", "course_title", "units", "instructor_name",
            "year", "session", "section", "syllabus_url", "dept_name", "subject_name", "college_name"]

    db_df = pd.DataFrame(cur.fetchall(), columns=cols)

    # Cast both to consistent types
    for frame in [df, db_df]:
        frame["section"]        = frame["section"].astype(str)
        frame["catalog_number"] = frame["catalog_number"].astype(str)
        frame["year"]           = frame["year"].astype(int)
        frame["units"]          = frame["units"].astype(float)

    df_sorted = df[cols].sort_values(cols).reset_index(drop=True)
    db_sorted = db_df.sort_values(cols).reset_index(drop=True)

    print(f"Original rows : {len(df_sorted)}")
    print(f"DB rows       : {len(db_sorted)}")

    missing = df_sorted.merge(db_sorted, how="left", indicator=True).query('_merge == "left_only"')
    if len(missing) > 0:
        print(f"\n{len(missing)} rows in CSV missing from DB:")
        print(missing)
    else:
        print("\nAll rows match!")


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

        print("\nValidating...")
        validate(cur, df)

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
