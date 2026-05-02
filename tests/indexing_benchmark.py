import asyncio
import os
import json
import asyncpg
from pathlib import Path
from dotenv import load_dotenv
from pgvector.asyncpg import register_vector

# ── Config ────────────────────────────────────────────────────────────────────
# Use absolute paths to ensure SQL and .env files are found reliably
BASE_DIR       = Path(__file__).resolve().parent
INDEX_SQL_PATH = BASE_DIR / "indexing_tests.sql"
ENV_PATH       = BASE_DIR.parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)

async def get_db_conn(db_name):
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=db_name,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    await register_vector(conn)
    return conn

async def run_individual_tests():
    # Ensure the SQL file exists before proceeding
    if not INDEX_SQL_PATH.exists():
        print(f"Error: Required test file not found at {INDEX_SQL_PATH}")
        return

    idx_conn = await get_db_conn("course_advisor")
    unidx_conn = await get_db_conn("course_advisor_test")

    try:
        # Get a real test vector from the database for the HNSW similarity search
        row = await idx_conn.fetchrow("SELECT embedding FROM syllabus_chunk LIMIT 1")
        if not row:
            print("Error: No data found in 'course_advisor' to run benchmarks.")
            return
        test_vector = row['embedding']

        # Define the mapping of queries to the index they test
        tests = [
            ("HNSW (Vector Search)", "idx_syllabus_embedding_hnsw"),
            ("FK: Chunk -> Section", "idx_chunk_section_id"),
            ("FK: Section -> Course", "idx_section_course_id"),
            ("FK: Section -> Instructor", "idx_section_instructor_id"),
            ("Composite: Section Lookup", "idx_section_lookup")
        ]

        # Read and parse the EXPLAIN queries from the SQL file
        with open(INDEX_SQL_PATH, 'r') as f:
            # Split queries by semicolon and filter for EXPLAIN statements
            queries = [q.strip() for q in f.read().split(';') if "EXPLAIN" in q]

        print(f"\n{'INDEX UNDER TEST':<30} | {'UNINDEXED (ms)':<15} | {'INDEXED (ms)':<15} | {'SPEEDUP'}")
        print("-" * 85)

        for i, query in enumerate(queries):
            # Boundary check to prevent IndexError if SQL file has more queries than defined in 'tests'
            if i >= len(tests):
                break

            label, index_name = tests[i]
            
            # Format query for asyncpg parameters ($1) instead of psql placeholders (%s)
            stmt = query.replace("%s", "$1")
            args = [test_vector] if "$1" in stmt else []

            # Execute on the unindexed baseline database
            res_un = await unidx_conn.fetchval(stmt, *args)
            time_un = json.loads(res_un)[0]['Execution Time']

            # Execute on the indexed production database
            res_idx = await idx_conn.fetchval(stmt, *args)
            time_idx = json.loads(res_idx)[0]['Execution Time']

            # Calculate speedup factor
            speedup = time_un / time_idx if time_idx > 0 else 0
            print(f"{label:<30} | {time_un:>14.2f} | {time_idx:>13.2f} | {speedup:.1f}x")

    except Exception as e:
        print(f"An error occurred during benchmark: {e}")
    finally:
        await idx_conn.close()
        await unidx_conn.close()

if __name__ == "__main__":
    asyncio.run(run_individual_tests())