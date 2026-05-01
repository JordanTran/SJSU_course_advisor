import asyncio
import os
import json
import asyncpg
from pathlib import Path
from dotenv import load_dotenv
from pgvector.asyncpg import register_vector
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()

async def get_db_conn(db_name):
    """Establishes connection and registers pgvector."""
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=db_name,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    await register_vector(conn)
    return conn

async def run_individual_tests():
    console.rule("[bold blue]Database Indexing Benchmark[/bold blue]")
    
    try:
        idx_conn = await get_db_conn("course_advisor")
        unidx_conn = await get_db_conn("course_advisor_test")
        
        # Get test vector for Test 1
        row = await idx_conn.fetchrow("SELECT embedding FROM syllabus_chunk LIMIT 1")
        if not row:
            console.print("[bold red]Error:[/bold red] No data found in 'course_advisor'.")
            return
        test_vector = row['embedding']

        # Define the mapping of queries to labels
        tests = [
            ("HNSW (Vector Search)", "idx_syllabus_embedding_hnsw"),
            ("FK: Chunk -> Section", "idx_chunk_section_id"),
            ("FK: Section -> Course", "idx_section_course_id"),
            ("FK: Section -> Instructor", "idx_section_instructor_id"),
            ("Composite: Section Lookup", "idx_section_lookup")
        ]

        # Load SQL queries
        with open('indexing_tests.sql', 'r') as f:
            queries = [q.strip() for q in f.read().split(';') if "EXPLAIN" in q]

        # Initialize Rich Table (matching concurrency_test style)
        perf_table = Table(title="Index Performance Comparison", show_lines=True)
        perf_table.add_column("Index Under Test", style="bold cyan", no_wrap=True)
        perf_table.add_column("Unindexed (ms)", justify="right")
        perf_table.add_column("Indexed (ms)",   justify="right")
        perf_table.add_column("Speedup",        justify="right", style="bold green")

        for i, query in enumerate(queries):
            if i >= len(tests): break
            label, _ = tests[i]
            
            stmt = query.replace("%s", "$1")
            args = [test_vector] if "$1" in stmt else []

            # Time Unindexed
            res_un = await unidx_conn.fetchval(stmt, *args)
            time_un = json.loads(res_un)[0]['Execution Time']

            # Time Indexed
            res_idx = await idx_conn.fetchval(stmt, *args)
            time_idx = json.loads(res_idx)[0]['Execution Time']

            # Calculate Speedup
            speedup_val = time_un / time_idx if time_idx > 0 else 0
            
            # Format rows
            perf_table.add_row(
                label,
                f"{time_un:.3f}",
                f"{time_idx:.3f}",
                f"{speedup_val:.1f}x"
            )

        console.print(perf_table)

    except Exception as e:
        console.print(f"[bold red]Benchmark failure:[/bold red] {e}")
    finally:
        if 'idx_conn' in locals(): await idx_conn.close()
        if 'unidx_conn' in locals(): await unidx_conn.close()

if __name__ == "__main__":
    asyncio.run(run_individual_tests())