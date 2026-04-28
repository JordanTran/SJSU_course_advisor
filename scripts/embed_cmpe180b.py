import csv
import json
import numpy as np
import os
import time

from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(BASE_DIR, "chunks_with_embeddings.csv")

# ── Gemini setup ──────────────────────────────────────────────────────────────
API_KEY    = os.environ.get("GOOGLE_API_KEY", "")
MODEL      = "gemini-embedding-001"
TASK_TYPE  = "RETRIEVAL_DOCUMENT"
DIMENSIONS = 768

client = genai.Client(api_key=API_KEY)

# ── Course metadata (one row per chunk; constant across all chunks) ────────────
META = {
    "subject":         "CMPE",
    "catalog_number":  "180B",
    "course_title":    "Database Systems",
    "units":           "3.0",
    "instructor_name": "Bond, Andrew",
    "year":            "2026",
    "session":         "Spring",
    "section":         "1",
    "syllabus_url":    "https://sjsu.campusconcourse.com/view_syllabus?course_id=84067",
    "dept_name":       "Computer Engineering",
    "subject_name":    "Computer Engineering",
    "college_name":    "Charles W Davidson College of Engineering",
    "delivery":        "In Person",
}

# ── Syllabus chunks ────────────────────────────────────────────────────────────
# Each entry: (chunk_title, chunk_text)
CHUNKS = [
    (
        "Course Info, Contact, and Communication",
        "Course: CMPE-180b, Database Systems, Section 01, Spring 2026. "
        "Instructor: Andrew Bond. Office Location: E281. Telephone: 408-666-7339. "
        "Email: andrew.bond@sjsu.edu. Office Hours: Tuesday at 3PM PST or by appointment. "
        "Class Days/Time: Tuesday and Thursday, 4:30–5:45 PM PST. Classroom: E325. "
        "Prerequisites: Classified graduate standing or graduate advisor consent. "
        "Canvas Website: https://sjsu.instructure.com/courses/1619288. "
        "This course is taught primarily face-to-face. Course materials, assignments, grading criteria, "
        "and exams are posted on Canvas at http://sjsu.instructure.com/. "
        "Students are responsible for checking Canvas regularly. "
        "Canvas tutorials are available at http://ges.sjsu.edu/canvasstudents. "
        "For Canvas or WebEx support, file a ticket at http://ges.sjsu.edu/instructional-design-help. "
        "Students should also check their SJSU email at http://my.sjsu.edu for instructor updates."
    ),
    (
        "Course Description and Required Textbook",
        "CMPE-180b is a comprehensive exploration of the latest advancements in enterprise technologies "
        "transforming the business landscape. Students gain a deep understanding of technology trends, "
        "their impact on application development, and future implications for enterprises. "
        "The course approaches database systems from a software engineering and development perspective. "
        "Required textbook: Database System Concepts, Seventh Edition. "
        "Authors: Avi Silberschatz, Henry F. Korth, S. Sudarshan. Publisher: McGraw-Hill. "
        "ISBN: 9780078022159. "
        "Lecture slides and other supplemental materials are distributed via the Canvas Portal."
    ),
    (
        "Course Learning Objectives (CLO 1–9)",
        "Upon successful completion of this course, students will be able to: "
        "CLO 1: Explain fundamental concepts of database systems, including data models, "
        "database architectures, and the role of DBMSs in modern applications. "
        "CLO 2: Design and interpret Entity-Relationship (ER) and Enhanced ER (EER) diagrams, "
        "and map them to relational schemas. "
        "CLO 3: Apply relational algebra and SQL (including advanced queries, joins, subqueries, "
        "triggers, and views) to query and manipulate data. "
        "CLO 4: Demonstrate understanding of database design principles, including normalization "
        "(up to BCNF), constraints, and schema refinement. "
        "CLO 5: Analyze and implement file organization, indexing, and query processing techniques "
        "to improve performance. "
        "CLO 6: Explain and apply transaction management concepts, including ACID properties, "
        "concurrency control, and recovery mechanisms. "
        "CLO 7: Evaluate and compare distributed databases, NoSQL systems, and emerging database "
        "technologies in terms of scalability, performance, and suitability for enterprise applications. "
        "CLO 8: Apply principles of database security, including authentication, access control, "
        "encryption, and SQL injection prevention. "
        "CLO 9: Design and implement a real-world database application via team project, integrating "
        "conceptual design, schema implementation, data loading, querying, and demonstration."
    ),
    (
        "Team Assignments, Exams, and Grading Policy",
        "Students must form teams of 2–4, elect a team leader, and choose a unique team name. "
        "The project should be representative of one or more topics covered in the course. "
        "All homework and projects are submitted only by the team leader and graded as team assignments. "
        "All final project deliverables are due at the start of class on the day of final presentations. "
        "Exams are a combination of multiple choice and short answer questions and are closed book. "
        "There is an interim midterm exam worth 10%, intended to assess student understanding. "
        "The final exam covers all semester topics and is worth 25% of the final grade. "
        "Grade weighting: 8 Homework Assignments (4% each) = 32%; 1 Term Project = 33%; "
        "1 Midterm = 10%; 1 Final = 25%. "
        "Grades are assigned on a curve. No extra credit is available. "
        "Grading scale: 100% = A+; 93–99% = A; 90–92% = A-; 87–89% = B+; 83–86% = B; 80–82% = B-; "
        "77–79% = C+; 73–76% = C; 70–72% = C-."
    ),
    (
        "Term Project Overview and Deliverables",
        "Students work in teams of 2–4 to design and implement a database-backed system solving a "
        "real-world problem or simulating an enterprise application. The term project is worth 33% of the final grade. "
        "Required elements: a conceptual data model, relational schema, SQL-based implementation, "
        "data loading and querying, transaction and concurrency design, performance/optimization elements, "
        "and a live demonstration with technical presentation. "
        "Grading breakdown: "
        "Project Report (3%): system overview, ER design, schema, normalization, SQL sample queries. "
        "Project Presentation (3%): 8–10 minute slide deck and oral presentation during final weeks. "
        "Live Demonstration (12%): functioning system with SQL backend, data ops, and UI or command interface. "
        "Code and Features (15%): GitHub repository with schema, scripts, queries, and documentation."
    ),
    (
        "Term Project Technical Constraints and Example Ideas",
        "Projects must use MySQL or PostgreSQL. "
        "The schema must include at least 6–8 interrelated tables. "
        "Required elements: ER Diagram; normalized schema in 3NF or BCNF; sample SQL queries "
        "(SELECT, JOINs, GROUP BY, etc.); DML scripts for data insertion and population; "
        "at least one stored procedure or trigger; transactions with concurrency controls. "
        "Optional: indexing strategy or performance profiling. "
        "Acceptable project examples: "
        "1. E-Commerce Platform Backend: products, users, carts, orders, reviews; multi-table joins, triggers, transactions. "
        "2. University Course Enrollment System: students, courses, prerequisites, instructors, rooms; "
        "enrollment constraints and concurrency simulation. "
        "3. Hospital or Clinic Record Management: patients, doctors, appointments, medications, billing; "
        "auditing and access control. "
        "4. Hotel Booking System: guests, rooms, rates, reservations; availability search and reporting. "
        "5. IoT or Smart Home Data Warehouse: simulated sensor data, stream ingestion, analytics queries."
    ),
    (
        "Term Project Timeline, Milestones, and Evaluation Criteria",
        "Project Proposal – Feb 15: 1-page team proposal and ERD sketch. "
        "Design Review Check-in – Mar 24 ERD, schema, normalization, and SQL plan. "
        "Presentation and Demo – May 5 & 7: In-class project presentations. "
        "Final Code and Report Submission – May 12: GitHub repository and PDF report due on Canvas. "
        "The schedule is subject to change with fair notice via Canvas. "
        "Evaluation criteria: correctness and complexity of schema design; code quality, SQL structure, "
        "and normalization; proper use of transactions and constraints; clarity and professionalism of "
        "the final report; teamwork and division of labor; presentation clarity and Q&A handling."
    ),
    (
        "Classroom Protocol and University Policies",
        "Students are expected to attend class on time and in person. "
        "Please refrain from using mobile devices in class except for taking notes or participating in class activities. "
        "Per University Policy S16-9, university-wide policy information relevant to all courses, such as "
        "academic integrity and accommodations, is available on the Office of Graduate and Undergraduate "
        "Programs' Syllabus Information page at http://www.sjsu.edu/gup/syllabusinfo/."
    ),
    (
        "Course Schedule: Weeks 1–15",
        "The schedule is subject to change with fair notice via Canvas. "
        "Week 1 (Jan 22): Course Introduction and Overview; Introduction to Database Systems – Ch. 1. "
        "Week 2 (Jan 27, Jan 29): DB System Architecture; Levels of Abstraction; Data Models and Database "
        "Languages; Intro to Relational Model – Ch. 2, 3. "
        "Week 3 (Jan 10, Jan 12): Database Design Process, ER Model Basics and Diagrams; Relational Design – Ch. 6, 7. "
        "Week 4 (Jan 17, Jan 19): Accessing SQL From a Programming Language; Functional Dependency Theory – Ch. 7, 6. "
        "Week 5 (Jan 24, Jan 26): Relational Algebra (extended) and practice; Last Day to Add/Drop (Tuesday) – Ch. 6. "
        "Week 6 (Mar 3, Mar 5): SQL: Basic Queries; Joins, Subqueries, Aggregations – Ch. 5. "
        "Week 7 (Mar 10, Mar 12): Semi-Structured and Object Data; Textual and Spatial Data – Ch. 8. "
        "Week 8 (Mar 17, Mar 19): Storage and File Structures, Disk Storage, RAID; "
        "File Organization, Indexing, Hashing – Ch. 12, 13. "
        "Week 9 (Mar 24, Mar 26): Midterm Review (Tuesday); Midterm Exam (Thursday). "
        "Week 10 (Mar 31, Apr 2): Spring Break – no class."
        "Week 11 (Apr 7, Apr 9): Transactions and ACID; Concurrency Control: Lock-Based Protocols – Ch. 15, 16. "
        "Week 12 (Apr 14, Apr 16): Transactions and Serializability; Concurrency Control and Other Protocols – Ch. 17, 18. "
        "Week 13 (Apr 21, Apr 23): Database Security (Access Control, Encryption); Recovery Techniques – Ch. 18. "
        "Week 14 (Apr 28, Apr 30): Distributed Databases and NoSQL; Big Data, NewSQL, Warehousing – Ch. 19–21. "
        "Week 15 (May 5, May 7): Project Presentations – Part I and Part II. "
        "Final Exam (May 14): Per SJSU exam schedule, 3:15–5:15 PM. Covers all course material. "
        "The schedule is subject to change with fair notice via Canvas."
    ),
] 


# ── Embedding helpers ─────────────────────────────────────────────────────────

def build_embedding_text(row: dict) -> str:
    """
    Combine course metadata + chunk content into a single document string.

    Putting structured context above the chunk body means the model encodes
    which course / department / instructor this belongs to alongside the
    actual syllabus content. Queries like "CS 101 grading policy" or
    "courses taught by Dr. Smith on machine learning" will therefore match
    the right chunks even when the chunk body alone wouldn't be enough.

    Output format:
        College: {college_name}
        Department: {dept_name}
        Subject: {subject_name} ({subject})
        Course: {subject} {catalog_number} — {course_title}
        Instructor: {instructor_name}
        Term: {session} {year} | Section {section} | {delivery}

        {chunk_title}

        {chunk_text}
    """
    def get(field: str) -> str:
        return (row.get(field) or "").strip()

    header = (
        f"College: {get('college_name')}\n"
        f"Department: {get('dept_name')}\n"
        f"Subject: {get('subject_name')} ({get('subject')})\n"
        f"Course: {get('subject')} {get('catalog_number')} — {get('course_title')}\n"
        f"Instructor: {get('instructor_name')}\n"
        f"Term: {get('session')} {get('year')} | "
        f"Section {get('section')} | {get('delivery')}"
    )

    parts = [header]
    if get("chunk_title"):
        parts.append(get("chunk_title"))
    if get("chunk_text"):
        parts.append(get("chunk_text"))

    return "\n\n".join(parts)


def _call_embed_batch_sync(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts in a single embed_content call.
    Returns a list of value arrays, one per input text, in the same order.

    API reference:
      client.models.embed_content(model, contents=[str, ...], config=...)
      Returns result.embeddings — a list of ContentEmbedding objects,
      each with a .values attribute (list[float]).
    """
    result = client.models.embed_content(
        model=MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=TASK_TYPE,
            output_dimensionality=DIMENSIONS,
        ),
    )
    # result.embeddings is a list aligned 1-to-1 with the input texts
    return [emb.values for emb in result.embeddings]


def embed(text: str, retries: int = 3, backoff: float = 2.0) -> list[float]:
    """Embed a single text with retry logic. Returns a DIMENSIONS-dim float list."""
    for attempt in range(retries):
        try:
            vecs = _call_embed_batch_sync([text])
            vec  = vecs[0]
            assert len(vec) == DIMENSIONS, f"Expected {DIMENSIONS} dims, got {len(vec)}"
            return vec
        except Exception as exc:
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                print(f"  [retry {attempt+1}] {exc} – waiting {wait}s")
                time.sleep(wait)
            else:
                raise


def _normalize(values: list[float]) -> list[float]:
    """L2-normalise a vector using numpy.

    gemini-embedding-001 only auto-normalises 3072-dim output. For any other
    dimension (768, 1536, …) you must normalise before cosine-similarity search,
    otherwise dot-product and cosine results will be wrong.
    """
    v    = np.array(values)
    norm = np.linalg.norm(v)
    return (v / norm).tolist() if norm > 0 else values


# ── Main ──────────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "subject", "catalog_number", "course_title", "units",
    "instructor_name", "year", "session", "section",
    "syllabus_url", "dept_name", "subject_name", "college_name",
    "delivery", "chunk_title", "chunk_text", "embedding",
]


def main():
    if not API_KEY:
        raise EnvironmentError("Set GOOGLE_API_KEY before running this script.")

    rows = []
    total = len(CHUNKS)
    for idx, (chunk_title, chunk_text) in enumerate(CHUNKS, start=1):
        row = {**META, "chunk_title": chunk_title, "chunk_text": chunk_text}
        doc  = build_embedding_text(row)

        print(f"[{idx:02d}/{total}] Embedding: {chunk_title!r}")
        vec = _normalize(embed(doc))
        row["embedding"] = json.dumps(vec)   # store as JSON array string
        rows.append(row)
        time.sleep(0.2)  # gentle rate-limit buffer

    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writerows(rows)

    print(f"\n✓ Wrote {len(rows)} chunks → {OUTPUT_CSV}")
    print(f"  Columns: {', '.join(FIELDNAMES)}")

if __name__ == "__main__":
    main()
