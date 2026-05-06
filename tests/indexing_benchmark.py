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

def make_table(title: str) -> Table:
    """Create a consistently styled Rich table."""
    table = Table(title=f"\n{title}", header_style="bold cyan")
    table.add_column("Query Scenario",  style="dim", width=32)
    table.add_column("Base Time",       justify="right")
    table.add_column("Idx Time",        justify="right", style="green")
    table.add_column("Base Hits",       justify="right")
    table.add_column("Idx Hits",        justify="right", style="blue")
    table.add_column("Speedup",         justify="right", style="bold green")
    table.add_column("I/O Efficiency",  justify="right", style="bold blue")
    return table

async def run_query(conn, stmt: str, args: list):
    """Run an EXPLAIN query and return the parsed plan."""
    if args:
        raw = await conn.fetchval(stmt, *args)
    else:
        raw = await conn.fetchval(stmt)
    return json.loads(raw)[0]

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
            console.print("[bold yellow]Warning:[/bold yellow] No syllabus data found to run RAG benchmarks.")
            return
        test_vector = row['embedding']

        # ── Test metadata ─────────────────────────────────────────────────────
        # is_vector=True  → replace %s with $1/$2 and bind test_vector twice
        # is_vector=False → no placeholders; query runs as-is with no args
        rag_tests = [
            {"label": "No filters (vector only)",    "is_vector": True},
            {"label": "Filter: catalog_number",      "is_vector": True},
            {"label": "Filter: instructor ILIKE",    "is_vector": True},
            {"label": "Filter: section",             "is_vector": True},
            {"label": "Filter: delivery",            "is_vector": True},
            {"label": "Filter: year + session",      "is_vector": True},
            {"label": "Heavy filter: full metadata", "is_vector": True},
        ]

        feedback_tests = [
            {"label": "No filters (ORDER BY date)",  "is_vector": False},
            {"label": "Filter: vote (is_positive)",  "is_vector": False},
            {"label": "Filter: session_id (exact)",  "is_vector": False},
            {"label": "Text search (ILIKE on both)", "is_vector": False},
        ]

        all_tests = rag_tests + feedback_tests

        # ── Parse SQL file ────────────────────────────────────────────────────
        with open(INDEX_SQL_PATH, encoding='utf-8') as f:
            raw = f.read()
            queries = [
                "EXPLAIN" + q.strip()
                for q in raw.split("EXPLAIN")
                if "ANALYZE" in q
            ]

        if len(queries) < len(all_tests):
            console.print(
                f"[bold yellow]Warning:[/bold yellow] Found {len(queries)} queries "
                f"but expected {len(all_tests)}. Some tests will be skipped."
            )

        # ── Run tests and collect rows ────────────────────────────────────────
        rag_rows      = []
        feedback_rows = []

        for i, query in enumerate(queries):
            if i >= len(all_tests):
                break

            test = all_tests[i]

            if test["is_vector"]:
                stmt = query.replace("%s", "$1", 1).replace("%s", "$2", 1)
                args = [test_vector, test_vector]
            else:
                stmt = query
                args = []

            plan_un  = await run_query(unidx_conn, stmt, args)
            plan_idx = await run_query(idx_conn,   stmt, args)

            time_un  = plan_un['Execution Time']
            hits_un  = extract_buffer_stats(plan_un)
            time_idx = plan_idx['Execution Time']
            hits_idx = extract_buffer_stats(plan_idx)

            speedup    = time_un / time_idx if time_idx > 0 else 0
            efficiency = hits_un / max(hits_idx, 1)

            row = (
                test["label"],
                f"{time_un:.2f}ms",
                f"{time_idx:.2f}ms",
                str(hits_un),
                str(hits_idx),
                f"{speedup:.1f}x",
                f"{efficiency:.1f}x",
            )

            if i < len(rag_tests):
                rag_rows.append(row)
            else:
                feedback_rows.append(row)

        # ── Print RAG table ───────────────────────────────────────────────────
        rag_table = make_table("Hybrid RAG Performance: Speed & I/O Efficiency")
        for r in rag_rows:
            rag_table.add_row(*r)
        console.print(rag_table)

        # ── Print feedback table ──────────────────────────────────────────────
        fb_table = make_table("Feedback Table Performance: Speed & I/O Efficiency")
        for r in feedback_rows:
            fb_table.add_row(*r)
        console.print(fb_table)

        console.print("\n[dim]Note: 'Hits' represent the number of 8KB data blocks accessed by the database engine.[/dim]")
        console.print("[dim]A higher I/O Efficiency means the index successfully bypassed unnecessary data scans.[/dim]\n")

    except Exception as e:
        console.print(f"[bold red]An error occurred during benchmarking:[/bold red] {e}")
    finally:
        await idx_conn.close()
        await unidx_conn.close()

if __name__ == "__main__":
    asyncio.run(run_individual_tests())
