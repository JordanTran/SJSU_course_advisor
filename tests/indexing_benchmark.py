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
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=db_name,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    await register_vector(conn)
    return conn

async def run_individual_tests():
    if not INDEX_SQL_PATH.exists():
        console.print(f"[bold red]Error:[/bold red] Required test file not found at {INDEX_SQL_PATH}")
        return

    idx_conn = await get_db_conn("course_advisor")
    unidx_conn = await get_db_conn("course_advisor_test")

    try:
        # Get a real test vector
        row = await idx_conn.fetchrow("SELECT embedding FROM syllabus_chunk LIMIT 1")
        if not row:
            console.print("[bold yellow]Warning:[/bold yellow] No data found to run benchmarks.")
            return
        test_vector = row['embedding']

        tests = [
            ("HNSW (Vector Search)", "idx_syllabus_embedding_hnsw"),
            ("FK: Chunk -> Section", "idx_chunk_section_id"),
            ("FK: Section -> Course", "idx_section_course_id"),
            ("FK: Section -> Instructor", "idx_section_instructor_id"),
            ("Composite: Section Lookup", "idx_section_lookup")
        ]

        with open(INDEX_SQL_PATH, 'r') as f:
            queries = [q.strip() for q in f.read().split(';') if "EXPLAIN" in q]

        # Create a Rich Table similar to the concurrency test
        table = Table(title="\nIndexing Performance Benchmark", header_style="bold cyan")
        table.add_column("Index Under Test", style="dim", width=30)
        table.add_column("Unindexed (ms)", justify="right")
        table.add_column("Indexed (ms)", justify="right")
        table.add_column("Speedup", justify="right", style="bold green")

        for i, query in enumerate(queries):
            if i >= len(tests):
                break

            label, _ = tests[i]
            stmt = query.replace("%s", "$1")
            args = [test_vector] if "$1" in stmt else []

            # Execute benchmarks
            res_un = await unidx_conn.fetchval(stmt, *args)
            time_un = json.loads(res_un)[0]['Execution Time']

            res_idx = await idx_conn.fetchval(stmt, *args)
            time_idx = json.loads(res_idx)[0]['Execution Time']

            speedup = time_un / time_idx if time_idx > 0 else 0
            
            # Format speedup color based on performance gain
            speedup_str = f"{speedup:.1f}x"
            if speedup < 1.5:
                speedup_str = f"[yellow]{speedup_str}[/yellow]"
            elif speedup > 10:
                speedup_str = f"[bold green]{speedup_str}[/bold green]"

            table.add_row(
                label, 
                f"{time_un:.2f}", 
                f"{time_idx:.2f}", 
                speedup_str
            )

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]An error occurred:[/bold red] {e}")
    finally:
        await idx_conn.close()
        await unidx_conn.close()

if __name__ == "__main__":
    asyncio.run(run_individual_tests())