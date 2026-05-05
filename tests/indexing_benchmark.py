import asyncio
import os
import json
import asyncpg
from pathlib import Path
from dotenv import load_dotenv
from pgvector.asyncpg import register_vector

# Import Rich components for a professional terminal UI
from rich.console import Console
from rich.table import Table

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).resolve().parent
INDEX_SQL_PATH = BASE_DIR / "indexing_tests.sql"
ENV_PATH       = BASE_DIR.parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)
console = Console()

async def get_db_conn(db_name):
    """Establish connection and register pgvector."""
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=db_name,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    await register_vector(conn)
    return conn

def extract_buffer_stats(plan_json):
    """
    Recursively sums 'Shared Hit Blocks' and 'Shared Read Blocks' from the plan.
    'Hits' represent 8KB data blocks the database had to access.
    """
    plan = plan_json['Plan']
    hits = plan.get('Shared Hit Blocks', 0) + plan.get('Shared Read Blocks', 0)
    
    # Also check sub-plans/children for hits
    if 'Plans' in plan:
        for subplan in plan['Plans']:
            hits += subplan.get('Shared Hit Blocks', 0) + subplan.get('Shared Read Blocks', 0)
            
    return hits

async def run_individual_tests():
    if not INDEX_SQL_PATH.exists():
        console.print(f"[bold red]Error:[/bold red] Required test file not found at {INDEX_SQL_PATH}")
        return

    # Connect to both indexed and unindexed databases
    idx_conn   = await get_db_conn("course_advisor")
    unidx_conn = await get_db_conn("course_advisor_test")

    try:
        # Get a real embedding so the vector query is realistic
        row = await idx_conn.fetchrow("SELECT embedding FROM syllabus_chunk LIMIT 1")
        if not row:
            console.print("[bold yellow]Warning:[/bold yellow] No data found to run benchmarks.")
            return
        test_vector = row['embedding']

        tests = [
            {"label": "No filters (vector only)", "indexes": "idx_syllabus_embedding_hnsw"},
            {"label": "Filter: catalog_number", "indexes": "idx_course_catalog_number"},
            {"label": "Filter: instructor ILIKE", "indexes": "idx_instructor_name_trgm"},
            {"label": "Filter: section", "indexes": "idx_section_section"},
            {"label": "Filter: delivery", "indexes": "idx_section_delivery"},
            {"label": "Filter: year + session", "indexes": "idx_section_lookup"},
            {"label": "Heavy Filter: full metadata", "indexes": "catalog, lookup, trgm, hnsw"},
        ]

        with open(INDEX_SQL_PATH, 'r') as f:
            raw = f.read()
            queries = [
                "EXPLAIN" + q.strip()
                for q in raw.split("EXPLAIN")
                if "ANALYZE" in q
            ]

        # ── Table Setup ────────────────────────────────────────────────────────
        table = Table(title="\nHybrid RAG Performance: Speed & I/O Efficiency", header_style="bold cyan")
        
        table.add_column("Query Scenario", style="dim", width=30)
        table.add_column("Base Time",     justify="right")
        table.add_column("Idx Time",      justify="right", style="green")
        table.add_column("Base Hits",     justify="right")
        table.add_column("Idx Hits",      justify="right", style="blue")
        table.add_column("Speedup",       justify="right", style="bold green")
        table.add_column("I/O Efficiency", justify="right", style="bold blue")

        for i, query in enumerate(queries):
            if i >= len(tests): break
            test = tests[i]

            # Bind vector to $1 and $2
            stmt = query.replace("%s", "$1", 1).replace("%s", "$2", 1)
            args = [test_vector, test_vector]

            # Run Unindexed (Baseline)
            res_un   = await unidx_conn.fetchval(stmt, *args)
            plan_un  = json.loads(res_un)[0]
            time_un  = plan_un['Execution Time']
            hits_un  = extract_buffer_stats(plan_un)

            # Run Indexed (Optimized)
            res_idx  = await idx_conn.fetchval(stmt, *args)
            plan_idx = json.loads(res_idx)[0]
            time_idx = plan_idx['Execution Time']
            hits_idx = extract_buffer_stats(plan_idx)

            # Performance Metrics
            speedup    = time_un / time_idx if time_idx > 0 else 0
            # If hits_idx is 0 (very rare but possible for cache), treat as 1 to avoid div by zero
            efficiency = hits_un / max(hits_idx, 1)

            table.add_row(
                test["label"],
                f"{time_un:.2f}ms",
                f"{time_idx:.2f}ms",
                str(hits_un),
                str(hits_idx),
                f"{speedup:.1f}x",
                f"{efficiency:.1f}x"
            )

        console.print(table)
        console.print("\n[dim]Note: 'Hits' represent the number of 8KB data blocks accessed by the database engine.[/dim]")
        console.print("[dim]A higher I/O Efficiency means the index successfully bypassed unnecessary data scans.[/dim]\n")

    except Exception as e:
        console.print(f"[bold red]An error occurred during benchmarking:[/bold red] {e}")
    finally:
        await idx_conn.close()
        await unidx_conn.close()

if __name__ == "__main__":
    asyncio.run(run_individual_tests())