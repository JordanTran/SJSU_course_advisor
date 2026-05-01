import asyncio
import os
import json
import asyncpg
from pathlib import Path
from dotenv import load_dotenv
from pgvector.asyncpg import register_vector

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR.parent / '.env'
SQL_PATH = BASE_DIR / 'indexing_tests.sql'

load_dotenv(dotenv_path=ENV_PATH)

async def run_benchmark():
    try:
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "course_advisor"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        await register_vector(conn)

        row = await conn.fetchrow("SELECT embedding FROM syllabus_chunk LIMIT 1")
        if not row:
            print("Error: No data found.")
            return
        test_vector = row['embedding']

        with open(SQL_PATH, 'r') as f:
            commands = [c.strip() for c in f.read().split(';') if c.strip()]

        print(f"\n{'QUERY SCENARIO':<35} | {'TIME':<10} | {'STRATEGY'}")
        print("-" * 80)

        relational_indexes_active = False

        for cmd in commands:
            try:
                # Track state for labeling
                if "CREATE INDEX" in cmd:
                    await conn.execute(cmd)
                    relational_indexes_active = True
                
                elif "DROP INDEX" in cmd:
                    await conn.execute(cmd)
                    relational_indexes_active = False

                elif "ORDER BY embedding <=>" in cmd:
                    is_baseline = "syllabus_chunk_baseline" in cmd
                    label = "Vector Search (Baseline)" if is_baseline else "Vector Search (Optimized)"
                    
                    stmt = cmd.replace("%s", "$1")
                    result = await conn.fetchval(stmt, test_vector)
                    plan = json.loads(result)[0]
                    print(f"{label:<35} | {plan['Execution Time']:>7.2f}ms | {plan['Plan']['Node Type']}")

                elif "JOIN section" in cmd:
                    label = "Relational Join (Optimized)" if relational_indexes_active else "Relational Join (Baseline)"
                    result = await conn.fetchval(cmd)
                    plan = json.loads(result)[0]
                    print(f"{label:<35} | {plan['Execution Time']:>7.2f}ms | {plan['Plan']['Node Type']}")
                
                else:
                    await conn.execute(cmd)

            except Exception as e:
                print(f"Status: Skipping/Error on command: {str(e)[:50]}...")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_benchmark())