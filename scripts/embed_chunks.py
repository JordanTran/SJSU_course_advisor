#!/usr/bin/env python3

import asyncio
import csv
import json
import numpy as np
import os
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

# ===========================================================================
#  CONFIG — edit these before running
# ===========================================================================

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV  = os.path.join(BASE_DIR, "chunks.csv")
OUTPUT_CSV = os.path.join(BASE_DIR, "chunks_with_embeddings.csv")

# Embedding dimensions: 128 / 256 / 512 / 768 / 1536 / 3072
# Recommended by Google: 768, 1536, or 3072.
DIMENSIONS = 768

# API key — reads from environment variable by default, or paste key directly
API_KEY    = os.environ.get("GOOGLE_API_KEY", "")

# To resume a previously interrupted run, set this to the path of the
# partial output CSV and re-run. Already-embedded rows will be skipped.
# Leave as empty string "" to start a fresh run.
RESUME_FROM = ""

# ===========================================================================

# ---------------------------------------------------------------------------
# Constants (don't edit)
# ---------------------------------------------------------------------------
MODEL     = "gemini-embedding-001"
TASK_TYPE = "RETRIEVAL_DOCUMENT"

# Number of chunks sent per embed_content call.
# The API accepts a list of strings in one call (each chunk = one list item).
# docs: https://ai.google.dev/gemini-api/docs/embeddings#generating-embeddings
# Input token limit per content item: 2,048 tokens.
# At ~500 tok/chunk, 100 chunks ≈ 50,000 tokens per call — well under limit.
BATCH_SIZE = 100

# Rate limits — set conservatively below the API maximums to leave headroom.
# Actual limits: 3,000 RPM / 1,000,000 TPM
# With BATCH_SIZE=100, we only need ~20 RPM — RPM is not a concern.
# TPM is the real ceiling: 950,000 TPM / 500 tok/chunk = 1,900 chunks/min
# → ~65 minutes for 123k chunks.
RPM_LIMIT      = 2_800   # kept for safety, will never be reached with batching
TPM_LIMIT      = 950_000 # tokens per minute — this is the active constraint
MAX_CONCURRENT = 20      # concurrent batch calls (each covers 100 chunks)

# Retry settings for 429 / transient errors
MAX_RETRIES  = 6
RETRY_BASE_S = 10        # seconds; doubles each attempt (10, 20, 40, 80 …)

REQUIRED_COLUMNS = {
    "subject", "catalog_number", "course_title", "instructor_name",
    "year", "session", "section", "delivery",
    "dept_name", "subject_name", "college_name",
    "chunk_title", "chunk_text",
}


# ---------------------------------------------------------------------------
# Text builder  (unchanged from batch version)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class RateLimiter:
    """
    Sliding-window rate limiter that enforces both RPM and TPM ceilings.

    Call await limiter.acquire(tokens) before each API call.
    It will sleep as long as needed to stay under both limits.

    With BATCH_SIZE=100, each acquire() call represents 1 request and
    ~50,000 tokens, so TPM is the only limit that ever triggers in practice.
    """

    def __init__(self, rpm: int, tpm: int) -> None:
        self._rpm      = rpm
        self._tpm      = tpm
        self._req_log: deque[float]             = deque()  # timestamps
        self._tok_log: deque[tuple[float, int]] = deque()  # (timestamp, tokens)
        self._lock     = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        async with self._lock:
            while True:
                now    = time.monotonic()
                cutoff = now - 60.0

                while self._req_log and self._req_log[0] < cutoff:
                    self._req_log.popleft()
                while self._tok_log and self._tok_log[0][0] < cutoff:
                    self._tok_log.popleft()

                rpm_ok = len(self._req_log) < self._rpm
                tpm_ok = sum(t for _, t in self._tok_log) + tokens < self._tpm

                if rpm_ok and tpm_ok:
                    self._req_log.append(now)
                    self._tok_log.append((now, tokens))
                    return

                wait = 0.1
                if not rpm_ok and self._req_log:
                    wait = max(wait, 60.0 - (now - self._req_log[0]) + 0.05)
                if not tpm_ok and self._tok_log:
                    wait = max(wait, 60.0 - (now - self._tok_log[0][0]) + 0.05)

                await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Resume helper
# ---------------------------------------------------------------------------
def load_existing_embeddings(path: str) -> dict[int, list[float] | None]:
    """
    Read a partial output CSV and return {row_index: embedding}.
    Rows with a non-null embedding are treated as already done.
    """
    result: dict[int, list[float] | None] = {}
    if not Path(path).exists():
        return result

    with open(path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            raw = row.get("embedding", "")
            try:
                emb = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                emb = None
            result[i] = emb

    done = sum(1 for v in result.values() if v is not None)
    print(f"  Resuming: {done:,} rows already embedded in '{path}' — skipping those.")
    return result


# ---------------------------------------------------------------------------
# Core API call — embeds a batch of texts in one request
# ---------------------------------------------------------------------------
def _call_embed_batch_sync(client: genai.Client, texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts in a single embed_content call.
    Returns a list of value arrays, one per input text, in the same order.

    API reference:
      client.models.embed_content(model, contents=[str, ...], config=...)
      Returns result.embeddings — a list of ContentEmbedding objects,
      each with a .values attribute (list[float]).
      docs: https://ai.google.dev/gemini-api/docs/embeddings#generating-embeddings
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


# ---------------------------------------------------------------------------
# Async batch worker
# ---------------------------------------------------------------------------
async def embed_batch(
    executor:  ThreadPoolExecutor,
    client:    genai.Client,
    limiter:   RateLimiter,
    semaphore: asyncio.Semaphore,
    indices:   list[int],
    texts:     list[str],
) -> list[tuple[int, list[float] | None]]:
    """
    Embed one batch (up to BATCH_SIZE chunks) with rate limiting and retry.
    Returns a list of (row_index, embedding_or_None) pairs.
    """
    # Rough token estimate: ~4 chars per token, across all texts in the batch
    batch_tokens = max(1, sum(len(t) for t in texts) // 4)

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            await limiter.acquire(batch_tokens)
            try:
                loop       = asyncio.get_running_loop()
                embeddings = await loop.run_in_executor(
                    executor, _call_embed_batch_sync, client, texts
                )
                # Zip results back to their original row indices
                return list(zip(indices, embeddings))

            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
                is_last       = attempt == MAX_RETRIES - 1

                if is_last:
                    print(
                        f"  ✗ Batch rows {indices[0]}–{indices[-1]}: "
                        f"giving up after {MAX_RETRIES} attempts — {exc}"
                    )
                    return [(i, None) for i in indices]

                wait  = RETRY_BASE_S * (2 ** attempt)
                label = "rate limited" if is_rate_limit else f"error ({exc})"
                print(
                    f"  ⚠ Batch rows {indices[0]}–{indices[-1]}: "
                    f"{label}, retrying in {wait}s …"
                )
                await asyncio.sleep(wait)

    return [(i, None) for i in indices]  # unreachable, satisfies type checker


# ---------------------------------------------------------------------------
# Step 1 – Validate and load CSV
# ---------------------------------------------------------------------------
def validate_csv() -> list[dict]:
    print(f"\n[1/3] Reading '{INPUT_CSV}' …")
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            print(
                f"ERROR: Input CSV is missing required columns: {sorted(missing)}\n"
                f"Found columns: {sorted(reader.fieldnames or [])}"
            )
            sys.exit(1)
        rows = list(reader)

    print(f"  {len(rows):,} rows loaded")
    return rows


# ---------------------------------------------------------------------------
# Step 2 – Embed all rows in batches
# ---------------------------------------------------------------------------
async def embed_all(
    rows:     list[dict],
    existing: dict[int, list[float] | None],
) -> dict[int, list[float] | None]:

    client    = genai.Client(api_key=API_KEY)
    limiter   = RateLimiter(rpm=RPM_LIMIT, tpm=TPM_LIMIT)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # Build (index, text) list for rows that still need embedding
    todo = [
        (i, build_embedding_text(row) or " ")
        for i, row in enumerate(rows)
        if existing.get(i) is None
    ]

    total   = len(rows)
    skipped = total - len(todo)
    n_calls = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE  # ceil division

    print(
        f"\n[2/3] Embedding {len(todo):,} rows across {n_calls:,} API calls "
        f"(batch size {BATCH_SIZE}, {skipped:,} already done, "
        f"{MAX_CONCURRENT} concurrent) …"
    )
    print(f"  Rate limits: {RPM_LIMIT:,} RPM / {TPM_LIMIT:,} TPM\n")

    results: dict[int, list[float] | None] = dict(existing)
    done_count = skipped

    # Slice todo into fixed-size batches and dispatch concurrently
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        batch_tasks = []
        for start in range(0, len(todo), BATCH_SIZE):
            chunk   = todo[start : start + BATCH_SIZE]
            indices = [i for i, _ in chunk]
            texts   = [t for _, t in chunk]
            batch_tasks.append(
                embed_batch(executor, client, limiter, semaphore, indices, texts)
            )

        for coro in asyncio.as_completed(batch_tasks):
            pairs = await coro
            for idx, embedding in pairs:
                results[idx] = embedding
            done_count += len(pairs)

            if done_count % 5_000 == 0 or done_count >= total:
                pct = done_count / total * 100
                print(f"  … {done_count:,} / {total:,} ({pct:.1f}%) complete")

    failed = sum(1 for i, _ in todo if results.get(i) is None)
    print(f"\n  Embedding complete — {failed:,} failed rows (will be stored as null)")
    return results


# ---------------------------------------------------------------------------
# Step 3 – Write output CSV
# ---------------------------------------------------------------------------
def write_output_csv(rows: list[dict], embedding_map: dict[int, list[float] | None]) -> None:
    print(f"\n[3/3] Writing output CSV to '{OUTPUT_CSV}' …")
    missing = 0

    with open(INPUT_CSV, newline="", encoding="utf-8") as csv_in:
        fieldnames = list(csv.DictReader(csv_in).fieldnames or []) + ["embedding"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csv_out:
        writer = csv.DictWriter(csv_out, fieldnames=fieldnames)
        writer.writeheader()

        for i, row in enumerate(rows):
            embedding = embedding_map.get(i)
            if embedding is None:
                missing += 1
            else:
                # Normalise before storing — required for non-3072 dimensions
                # so that cosine similarity == dot product (faster ANN queries).
                embedding = _normalize(embedding)

            # Stored as a compact JSON array string; load with:
            #   json.loads(row["embedding"])
            #   np.array(json.loads(row["embedding"]))
            row["embedding"] = json.dumps(embedding)
            writer.writerow(row)

    print(f"  Done — {missing:,} rows have null embeddings (API errors or empty text)")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _normalize(values: list[float]) -> list[float]:
    """L2-normalise a vector using numpy.

    gemini-embedding-001 only auto-normalises 3072-dim output. For any other
    dimension (768, 1536, …) you must normalise before cosine-similarity search,
    otherwise dot-product and cosine results will be wrong.
    """
    v    = np.array(values)
    norm = np.linalg.norm(v)
    return (v / norm).tolist() if norm > 0 else values


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if not API_KEY:
        print(
            "ERROR: No API key found.\n"
            "  Set the GOOGLE_API_KEY environment variable, "
            "or set API_KEY directly in the CONFIG section at the top of this file."
        )
        sys.exit(1)

    rows = validate_csv()

    # ── Resume mode ───────────────────────────────────────────────────────
    existing: dict[int, list[float] | None] = {}
    if RESUME_FROM:
        existing = load_existing_embeddings(RESUME_FROM)
    else:
        # Auto-resume from OUTPUT_CSV if it already exists
        if Path(OUTPUT_CSV).exists():
            print(f"\n  Found existing output at '{OUTPUT_CSV}'.")
            answer = input("  Resume from it? [y/N] ").strip().lower()
            if answer == "y":
                existing = load_existing_embeddings(OUTPUT_CSV)

    # ── Embed ─────────────────────────────────────────────────────────────
    embedding_map = asyncio.run(embed_all(rows, existing))

    # ── Write output ──────────────────────────────────────────────────────
    write_output_csv(rows, embedding_map)

    total   = len(rows)
    failed  = sum(1 for v in embedding_map.values() if v is None)
    success = total - failed
    print(
        f"\n✅  All done!\n"
        f"    Output  : {OUTPUT_CSV}\n"
        f"    Success : {success:,} / {total:,} rows embedded\n"
        f"    Failed  : {failed:,} rows (null embedding)\n"
        f"    Load embeddings with: np.array(json.loads(row['embedding']))\n"
    )

    if failed:
        print(
            f"  ┌─ TIP ──────────────────────────────────────────────────────┐\n"
            f"  │  To retry failed rows, set at the top of this file:        │\n"
            f"  │    RESUME_FROM = '{OUTPUT_CSV}'  │\n"
            f"  └────────────────────────────────────────────────────────────┘"
        )


if __name__ == "__main__":
    main()
