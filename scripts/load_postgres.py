"""
load_postgres.py
================
Populates the PostgreSQL database from two xlsx files:

  cmpe_syllabi_fillednew.xlsx  — course_title, department, catalog_number,
                                  delivery, units, college, session, year,
                                  section, source_url
  cmpe_syllabi.xlsx            — instructor name (joined on source_url)

Tables populated (in FK order):
  department  →  course  →  instructor  →  section

Usage:
    python3 load_postgres.py
    python3 load_postgres.py --dry-run       # parse only, no DB writes
    python3 load_postgres.py --clear         # DELETE existing rows first

Requirements:
    pip install psycopg2-binary openpyxl

Configure via env vars or edit PG_DSN below:
    export PG_DSN="postgresql://user:password@localhost:5432/your_db"
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from openpyxl import load_workbook

# ── connection ─────────────────────────────────────────────────────────────
PG_DSN = os.getenv("PG_DSN", "postgresql://ubuntu:ubuntu@localhost:5432/cmpe_syllabi")


# ── file paths ─────────────────────────────────────────────────────────────
FILE_FILLED = Path("cmpe_syllabi_fillednew.xlsx")
FILE_BASE   = Path("cmpe_syllabi.xlsx")

# ── department seed ────────────────────────────────────────────────────────
# The xlsx only has "CMPE" — the schema needs a row in department first.
# Extend this dict if you load other departments later.
DEPARTMENT_SEED = {
    "CMPE": {
        "department_name": "Computer Engineering",
        "college": "Charles W Davidson College of Engineering",
    }
}

# ── helpers ────────────────────────────────────────────────────────────────

def clean(val):
    """Strip whitespace; return None for empty/null values."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def norm_section(val):
    """
    Normalise section numbers:
      1  →  '01'
      49 →  '49'
      None → '01'  (default when missing)
    """
    if val is None:
        return "01"
    s = str(val).strip().lstrip("0") or "0"
    try:
        return str(int(s)).zfill(2)
    except ValueError:
        return s


def norm_units(val):
    """Extract integer units from '3', '3.0', '3 Unit(s)' etc."""
    if val is None:
        return None
    m = re.search(r"(\d+)", str(val))
    return int(m.group(1)) if m else None


def norm_delivery(val):
    """Normalise delivery mode to a consistent short string."""
    if not val:
        return None
    v = str(val).strip()
    mapping = {
        "in person":            "In Person",
        "face to face":         "In Person",
        "hybrid":               "Hybrid",
        "fully online":         "Online",
        "synchronous online":   "Online",
        "asynchronous online":  "Online",
        "async online":         "Online",
        "online":               "Online",
        "mixed mode":           "Hybrid",
    }
    return mapping.get(v.lower(), v)


# ── xlsx readers ───────────────────────────────────────────────────────────

def read_filled(path: Path) -> dict:
    """
    Read cmpe_syllabi_fillednew.xlsx.
    Returns dict keyed by source_url.
    Columns: [0]course_title [1]department [2]catalog_number [3]course_code
             [4]session [5]year [6]section [7]delivery [8]units
             [9]start_date [10]end_date [11]modified_date [12]college
             [13]department2 [14]description [15]prerequisites
             [16]grading_basis [17]source_url
    """
    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    data = {}
    skipped = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        url = clean(row[17])
        if not url:
            skipped += 1
            continue
        data[url] = {
            "course_title":   clean(row[0]),
            "department":     clean(row[1]) or "CMPE",
            "catalog_number": clean(str(row[2])) if row[2] is not None else None,
            "session":        clean(row[4]),
            "year":           int(row[5]) if row[5] else None,
            "section":        norm_section(row[6]),
            "delivery":       norm_delivery(row[7]),
            "units":          norm_units(row[8]),
            "college":        clean(row[12]),
            "source_url":     url,
        }
    wb.close()
    print(f"  {path.name}: {len(data)} rows loaded, {skipped} skipped (no URL)")
    return data


def read_base(path: Path) -> dict:
    """
    Read cmpe_syllabi.xlsx.
    Returns dict keyed by source_url with instructor name.
    Columns: [0]course_title [1]subject [2]catalog_number [3]course_code
             [4]session [5]year [6]section [7]instructor [8]source_url
    """
    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    data = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        url = clean(row[8])
        if not url:
            continue
        data[url] = {
            "instructor": clean(row[7]),
        }
    wb.close()
    print(f"  {path.name}: {len(data)} rows loaded")
    return data


def merge(filled: dict, base: dict) -> list:
    """
    Join on source_url. Instructor comes from base; everything else from filled.
    Rows in filled but not in base get instructor=None (handled as 'Unknown').
    """
    merged = []
    for url, f in filled.items():
        b = base.get(url, {})
        merged.append({**f, "instructor": b.get("instructor")})
    return merged


# ── validation ─────────────────────────────────────────────────────────────

def validate(rows: list) -> list:
    """
    Remove rows missing required fields.
    Logs a warning for each skipped row.
    """
    clean_rows = []
    skipped = 0
    for r in rows:
        missing = []
        if not r.get("course_title"):   missing.append("course_title")
        if not r.get("catalog_number"): missing.append("catalog_number")
        if not r.get("year"):           missing.append("year")
        if not r.get("session"):        missing.append("session")
        if missing:
            print(f"  WARNING skip url={r.get('source_url','?')[:60]}  missing={missing}")
            skipped += 1
            continue
        # Default units to 3 if missing (most CMPE courses are 3 units)
        if r.get("units") is None:
            r["units"] = 3
        # Default college if missing
        if not r.get("college"):
            r["college"] = "Charles W Davidson College of Engineering"
        # Default delivery if missing
        if not r.get("delivery"):
            r["delivery"] = None
        # Default instructor to 'Unknown' if missing
        if not r.get("instructor"):
            r["instructor"] = "Unknown"
        clean_rows.append(r)
    print(f"  Validation: {len(clean_rows)} ok, {skipped} skipped")
    return clean_rows


# ── database loader ────────────────────────────────────────────────────────

def load_to_db(rows: list, conn, clear: bool = False):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if clear:
        print("\n  Clearing existing rows ...")
        # Delete in FK reverse order
        for tbl in ("section", "course", "instructor", "department"):
            cur.execute(f"DELETE FROM {tbl}")
        conn.commit()
        print("  Done.")

    # ── 1. DEPARTMENT ──────────────────────────────────────────────────
    print("\n  Loading department ...")
    # Collect unique departments from data
    dept_colleges = {}
    for r in rows:
        dept = r["department"]
        college = r.get("college") or DEPARTMENT_SEED.get(dept, {}).get("college", "")
        if dept not in dept_colleges:
            dept_colleges[dept] = college

    # Merge with seed
    for dept, seed in DEPARTMENT_SEED.items():
        if dept not in dept_colleges:
            dept_colleges[dept] = seed["college"]

    dept_names = {
        "CMPE": "Computer Engineering",
        "CS":   "Computer Science",
        "EE":   "Electrical Engineering",
        "SE":   "Software Engineering",
    }

    dept_inserted = dept_skipped = 0
    for dept, college in dept_colleges.items():
        name = dept_names.get(dept, dept + " Department")
        cur.execute("""
            INSERT INTO department (department, department_name, college)
            VALUES (%s, %s, %s)
            ON CONFLICT (department) DO UPDATE
                SET department_name = EXCLUDED.department_name,
                    college         = EXCLUDED.college
        """, (dept, name, college))
        if cur.rowcount > 0:
            dept_inserted += 1
        else:
            dept_skipped += 1

    conn.commit()
    print(f"    departments: {dept_inserted} upserted, {dept_skipped} unchanged")

    # ── 2. COURSE ──────────────────────────────────────────────────────
    print("  Loading course ...")

    # Deduplicate: one row per (department, catalog_number)
    # Keep the row with the most complete data
    course_map = {}   # (dept, cat_num) -> {course_title, units, dept}
    for r in rows:
        key = (r["department"], r["catalog_number"])
        if key not in course_map:
            course_map[key] = {
                "department":     r["department"],
                "catalog_number": r["catalog_number"],
                "course_title":   r["course_title"],
                "units":          r["units"],
            }
        else:
            # Prefer row with non-null units
            if course_map[key]["units"] is None and r["units"] is not None:
                course_map[key]["units"] = r["units"]

    course_id_cache = {}   # (dept, cat_num) -> course_id
    course_inserted = course_skipped = 0

    for (dept, cat), c in course_map.items():
        cur.execute("""
            INSERT INTO course (department, catalog_number, course_title, units)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (department, catalog_number) DO UPDATE
                SET course_title = EXCLUDED.course_title,
                    units        = EXCLUDED.units
            RETURNING course_id
        """, (c["department"], c["catalog_number"], c["course_title"], c["units"]))
        row = cur.fetchone()
        course_id_cache[(dept, cat)] = row["course_id"]
        if cur.rowcount > 0:
            course_inserted += 1
        else:
            course_skipped += 1

    conn.commit()
    print(f"    courses: {course_inserted} upserted  ({len(course_map)} unique)")

    # ── 3. INSTRUCTOR ──────────────────────────────────────────────────
    print("  Loading instructor ...")

    unique_instructors = {r["instructor"] for r in rows if r.get("instructor")}
    instructor_id_cache = {}   # name -> instructor_id
    instr_inserted = 0

    for name in sorted(unique_instructors):
        cur.execute("""
            INSERT INTO instructor (instructor_name)
            VALUES (%s)
            ON CONFLICT (instructor_name) DO NOTHING
            RETURNING instructor_id
        """, (name,))
        returned = cur.fetchone()
        if returned:
            instructor_id_cache[name] = returned["instructor_id"]
            instr_inserted += 1

    # Fetch IDs for instructors that already existed (ON CONFLICT DO NOTHING)
    missing = unique_instructors - set(instructor_id_cache.keys())
    if missing:
        cur.execute(
            "SELECT instructor_id, instructor_name FROM instructor WHERE instructor_name = ANY(%s)",
            (list(missing),)
        )
        for row in cur.fetchall():
            instructor_id_cache[row["instructor_name"]] = row["instructor_id"]

    conn.commit()
    print(f"    instructors: {instr_inserted} inserted, "
          f"{len(unique_instructors) - instr_inserted} already existed  "
          f"({len(unique_instructors)} unique)")

    # ── 4. SECTION ────────────────────────────────────────────────────
    print("  Loading section ...")

    section_inserted = section_skipped = section_error = 0

    for r in rows:
        dept    = r["department"]
        cat     = r["catalog_number"]
        course_id = course_id_cache.get((dept, cat))
        if course_id is None:
            section_error += 1
            continue

        instr_name = r.get("instructor") or "Unknown"
        instr_id   = instructor_id_cache.get(instr_name)
        if instr_id is None:
            # Should not happen but guard anyway
            cur.execute(
                "INSERT INTO instructor (instructor_name) VALUES (%s) RETURNING instructor_id",
                (instr_name,)
            )
            instr_id = cur.fetchone()["instructor_id"]
            instructor_id_cache[instr_name] = instr_id

        try:
            cur.execute("""
                INSERT INTO section
                    (course_id, year, session, section,
                     instructor_id, delivery, syllabus_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (course_id, year, session, section)
                DO UPDATE SET
                    instructor_id = EXCLUDED.instructor_id,
                    delivery      = EXCLUDED.delivery,
                    syllabus_url  = EXCLUDED.syllabus_url
            """, (
                course_id,
                r["year"],
                r["session"],
                r["section"],
                instr_id,
                r.get("delivery"),
                r.get("source_url"),
            ))
            section_inserted += 1
        except Exception as e:
            conn.rollback()
            section_error += 1
            print(f"    ERROR row {r.get('source_url','?')[:60]}: {e}")
            continue

    conn.commit()
    print(f"    sections: {section_inserted} upserted, "
          f"{section_skipped} skipped, {section_error} errors")

    cur.close()


# ── summary query ──────────────────────────────────────────────────────────

def print_summary(conn):
    cur = conn.cursor()
    print("\n  ┌─────────────────┬──────────┐")
    print(  "  │ Table           │     Rows │")
    print(  "  ├─────────────────┼──────────┤")
    for tbl in ("department", "course", "instructor", "section"):
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        n = cur.fetchone()[0]
        print(f"  │ {tbl:<15} │ {n:>8} │")
    print(  "  └─────────────────┴──────────┘")

    # Top 5 instructors by section count
    cur.execute("""
        SELECT i.instructor_name, COUNT(*) AS cnt
        FROM section s
        JOIN instructor i USING (instructor_id)
        GROUP BY i.instructor_id
        ORDER BY cnt DESC
        LIMIT 5
    """)
    print("\n  Top instructors by section count:")
    for row in cur.fetchall():
        print(f"    {row[0]:<40} {row[1]} sections")

    # Year range
    cur.execute("SELECT MIN(year), MAX(year) FROM section")
    lo, hi = cur.fetchone()
    if lo:
        print(f"\n  Year range: {lo} → {hi}")

    cur.close()


# ── main ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",  action="store_true",
                    help="Parse files and validate but do not write to DB")
    ap.add_argument("--clear",    action="store_true",
                    help="Delete all rows from target tables before inserting")
    ap.add_argument("--filled",   default=str(FILE_FILLED),
                    help="Path to cmpe_syllabi_fillednew.xlsx")
    ap.add_argument("--base",     default=str(FILE_BASE),
                    help="Path to cmpe_syllabi.xlsx (has instructor column)")
    ap.add_argument("--dsn",      default=PG_DSN,
                    help="PostgreSQL DSN string")
    args = ap.parse_args()

    filled_path = Path(args.filled)
    base_path   = Path(args.base)

    for p in (filled_path, base_path):
        if not p.exists():
            print(f"File not found: {p}")
            sys.exit(1)

    print("\nReading xlsx files ...")
    filled = read_filled(filled_path)
    base   = read_base(base_path)

    print("\nMerging on source_url ...")
    rows = merge(filled, base)
    print(f"  Merged rows: {len(rows)}")

    print("\nValidating ...")
    rows = validate(rows)

    if args.dry_run:
        print("\n[DRY RUN] — no database writes.")
        print(f"  Would insert up to {len(rows)} sections.")
        unique_courses  = len({(r['department'], r['catalog_number']) for r in rows})
        unique_instrs   = len({r['instructor'] for r in rows if r['instructor']})
        unique_depts    = len({r['department'] for r in rows})
        print(f"  Unique departments : {unique_depts}")
        print(f"  Unique courses     : {unique_courses}")
        print(f"  Unique instructors : {unique_instrs}")
        return

    print(f"\nConnecting to database ...")
    try:
        conn = psycopg2.connect(args.dsn)
        conn.autocommit = False
        print("  Connected.")
    except Exception as e:
        print(f"  Connection failed: {e}")
        sys.exit(1)

    try:
        load_to_db(rows, conn, clear=args.clear)
        print_summary(conn)
    except Exception as e:
        conn.rollback()
        print(f"\nFatal error: {e}")
        import traceback; traceback.print_exc()
    finally:
        conn.close()

    print("\nDone.\n")


if __name__ == "__main__":
    main()