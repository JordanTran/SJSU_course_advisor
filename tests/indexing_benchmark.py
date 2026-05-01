import asyncio
import os
import json
import asyncpg
from pathlib import Path
from dotenv import load_dotenv
from pgvector.asyncpg import register_vector

# Setup Paths
BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR.parent / '.env'
SQL_PATH = BASE_DIR / 'indexing_tests.sql'

load_dotenv(dotenv_path=ENV_PATH)

async def run_benchmark():
    # 1. Connect using asyncpg (Avoids psycopg2/cmake issues)
    try:
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
        await register_vector(conn)
    except Exception as e:
        print(f"Connection Error: {e}")
        return

    # 2. Get Test Data
    row = await conn.fetchrow("SELECT embedding FROM syllabus_chunk LIMIT 1")
    if not row:
        print("No data in syllabus_chunk table.")
        return
    test_vector = row['embedding']

    # 3. Read and Split SQL file
    with open(SQL_PATH, 'r') as f:
        # Split by semicolon and ignore comments/empty lines
        content = f.read()
        commands = [c.strip() for c in content.split(';') if c.strip() and not c.startswith('--')]

    print(f"\n{'TEST SCENARIO':<35} | {'EXECUTION TIME':<15} | {'NODE TYPE'}")
    print("-" * 80)

    for cmd in commands:
        try:
            # Handle Vector Search Tests
            if "ORDER BY embedding <=>" in cmd:
                # Determine label based on context
                label = "Vector Search (Optimized)" if "idx_hnsw_embedding" in cmd else "Vector Search (Baseline)"
                
                # Replace %s with $1 for asyncpg
                stmt = cmd.replace("%s", "$1")
                raw_plan = await conn.fetchval(stmt, test_vector)
                plan = json.loads(raw_plan)[0]
                
                print(f"{label:<35} | {plan['Execution Time']:>10.2f} ms | {plan['Plan']['Node Type']}")

            # Handle Join Test
            elif "JOIN section" in cmd:
                raw_plan = await conn.fetchval(cmd)
                plan = json.loads(raw_plan)[0]
                print(f"{'Complex Relational Join':<35} | {plan['Execution Time']:>10.2f} ms | {plan['Plan']['Node Type']}")

            # Handle Setup (CREATE/DROP INDEX)
            else:
                await conn.execute(cmd)
                if "CREATE INDEX" in cmd:
                    name = cmd.split("INDEX ")[1].split(" ")[0]
                    print(f"Index Created: {name}")

        except Exception as e:
            print(f"Query Error: {e}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(run_benchmark())