import psycopg2
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_real_vector(cur):
    """Fetch a real vector from your DB to ensure the HNSW index is actually traversed."""
    cur.execute("SELECT embedding FROM syllabus_chunk LIMIT 1")
    return cur.fetchone()[0]

def run_benchmark():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        dbname=os.getenv("DB_NAME", "course_advisor"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Get a real vector for the test
    vector = get_real_vector(cur)
    
    # Read the SQL file
    sql_path = os.path.join(os.path.dirname(__file__), "performance_tests.sql")
    with open(sql_path, 'r') as f:
        sql_commands = f.read().split(';')

    print(f"{'QUERY SCENARIO':<35} | {'TIME':<10} | {'STRATEGY'}")
    print("-" * 70)

    for cmd in sql_commands:
        clean_cmd = cmd.strip()
        if not clean_cmd: continue

        # Handle Vector Search Commands (Injecting the real vector)
        if "ORDER BY embedding <=>" in clean_cmd:
            label = "Vector Search (Index)" if "idx_hnsw_embedding" in sql_commands[sql_commands.index(cmd)-1] else "Vector Search (Baseline)"
            cur.execute(clean_cmd, (vector,))
            plan = cur.fetchone()[0][0]
            print(f"{label:<35} | {plan['Execution Time']:>7.2f}ms | {plan['Plan']['Node Type']}")

        # Handle the Join Query
        elif "JOIN section" in clean_cmd:
            cur.execute(clean_cmd)
            plan = cur.fetchone()[0][0]
            print(f"{'Complex Relational Join':<35} | {plan['Execution Time']:>7.2f}ms | {plan['Plan']['Node Type']}")
        
        # Execute Setup/Drop/Create commands quietly
        else:
            cur.execute(clean_cmd)

    cur.close()
    conn.close()

if __name__ == "__main__":
    run_benchmark()