"""
test_concurrency.py — Concurrency stress-test for the Course Advisor API.

Tests three scenarios:
  1. Burst   — all requests fired simultaneously
  2. Ramp    — requests added progressively to simulate growing load
  3. Sustain — steady stream of requests over a longer window

Install deps:
    pip install httpx rich
"""

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from rich.console import Console
from rich.table import Table

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL     = "http://localhost:8000"
TIMEOUT      = 60.0   # seconds per request; LLM calls can be slow

# Burst: fire all requests at once. 10 == _POOL_MAX_CONN, so this hits the
# ceiling. Try 15–20 to intentionally trigger 503s and verify pool exhaustion handling.
BURST_N      = 10

# Ramp: start at RAMP_STEP concurrent requests, add RAMP_STEP each wave up to
# RAMP_MAX. Surfaces the exact concurrency level where latency climbs or errors appear.
RAMP_MAX     = 10
RAMP_STEP    = 2

# Sustain: send SUSTAIN_RPS requests every second for SUSTAIN_DUR seconds.
# 3 req/s for 15s = 45 total — enough to observe steady-state behaviour without
# hammering the LLM API budget during development.
SUSTAIN_RPS  = 3
SUSTAIN_DUR  = 15.0   # seconds

SKIP_BURST   = False
SKIP_RAMP    = False
SKIP_SUSTAIN = False

console = Console()

# ── Sample payloads ───────────────────────────────────────────────────────────
# Edit these to match courses that actually exist in your database.

SAMPLE_REQUESTS = [
    {"question": "What is the grading policy?",          "course_name": "ISE 201"},
    {"question": "How many units is this course?",       "course_name": "ISE 201"},
    {"question": "What is the late work policy?",        "course_name": "ISE 201"},
    {"question": "Who is the instructor?",               "course_name": "ISE 201"},
    {"question": "What textbook is required?",           "course_name": "ISE 201"},
    {"question": "When are office hours?",               "course_name": "ISE 201"},
    {"question": "What is the attendance policy?",       "course_name": "ISE 201"},
    {"question": "Is there a final exam?",               "course_name": "ISE 201"},
    {"question": "What topics are covered week 1?",      "course_name": "ISE 201"},
    {"question": "What is the course description?",      "course_name": "ISE 201"},
]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RequestResult:
    index: int
    status: int                    # HTTP status, or -1 for network error
    latency_s: float
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == 200


@dataclass
class ScenarioSummary:
    name: str
    results: list[RequestResult] = field(default_factory=list)
    wall_time_s: float = 0.0

    # ── Derived stats ─────────────────────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def successes(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failures(self) -> int:
        return self.total - self.successes

    @property
    def success_rate(self) -> float:
        return self.successes / self.total * 100 if self.total else 0.0

    @property
    def latencies(self) -> list[float]:
        return [r.latency_s for r in self.results if r.ok]

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies) if self.latencies else float("nan")

    @property
    def p95(self) -> float:
        lats = sorted(self.latencies)
        idx  = max(0, int(len(lats) * 0.95) - 1)
        return lats[idx] if lats else float("nan")

    @property
    def p99(self) -> float:
        lats = sorted(self.latencies)
        idx  = max(0, int(len(lats) * 0.99) - 1)
        return lats[idx] if lats else float("nan")

    @property
    def mean(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else float("nan")

    @property
    def throughput(self) -> float:
        return self.total / self.wall_time_s if self.wall_time_s else 0.0

    def status_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            key = str(r.status) if r.status != -1 else "network_error"
            counts[key] = counts.get(key, 0) + 1
        return counts


# ── Core request helper ───────────────────────────────────────────────────────

async def send_request(
    client: httpx.AsyncClient,
    base_url: str,
    index: int,
    payload: dict,
    timeout: float,
) -> RequestResult:
    start = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url}/ask",
            json=payload,
            timeout=timeout,
        )
        latency = time.perf_counter() - start
        return RequestResult(index=index, status=response.status_code, latency_s=latency)
    except Exception as exc:
        latency = time.perf_counter() - start
        return RequestResult(index=index, status=-1, latency_s=latency, error=str(exc))


# ── Scenarios ─────────────────────────────────────────────────────────────────

async def run_burst(base_url: str, n: int, timeout: float) -> ScenarioSummary:
    """Fire all N requests at the same instant."""
    summary = ScenarioSummary(name=f"Burst ({n} simultaneous)")
    payloads = [SAMPLE_REQUESTS[i % len(SAMPLE_REQUESTS)] for i in range(n)]

    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        tasks = [
            send_request(client, base_url, i, payloads[i], timeout)
            for i in range(n)
        ]
        summary.results = list(await asyncio.gather(*tasks))
        summary.wall_time_s = time.perf_counter() - t0

    return summary


async def run_ramp(base_url: str, max_concurrent: int, step: int, timeout: float) -> ScenarioSummary:
    """
    Gradually increase concurrency from `step` up to `max_concurrent`,
    adding `step` more parallel requests each wave.
    """
    summary = ScenarioSummary(name=f"Ramp (1 → {max_concurrent} concurrent, step {step})")
    index   = 0

    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        concurrency = step
        while concurrency <= max_concurrent:
            payloads = [SAMPLE_REQUESTS[index % len(SAMPLE_REQUESTS)] for _ in range(concurrency)]
            tasks    = [
                send_request(client, base_url, index + i, payloads[i], timeout)
                for i in range(concurrency)
            ]
            wave_results = list(await asyncio.gather(*tasks))
            summary.results.extend(wave_results)
            index       += concurrency
            concurrency += step
            await asyncio.sleep(0.1)   # small gap between waves
        summary.wall_time_s = time.perf_counter() - t0

    return summary


async def run_sustain(base_url: str, rps: int, duration_s: float, timeout: float) -> ScenarioSummary:
    """
    Send `rps` requests per second for `duration_s` seconds using a token-bucket
    approach (no drift accumulation).
    """
    summary   = ScenarioSummary(name=f"Sustain ({rps} req/s for {duration_s:.0f}s)")
    all_tasks: list[asyncio.Task] = []
    index     = 0

    async with httpx.AsyncClient() as client:
        t0       = time.perf_counter()
        deadline = t0 + duration_s
        interval = 1.0 / rps

        while True:
            now = time.perf_counter()
            if now >= deadline:
                break
            payload = SAMPLE_REQUESTS[index % len(SAMPLE_REQUESTS)]
            task    = asyncio.create_task(
                send_request(client, base_url, index, payload, timeout)
            )
            all_tasks.append(task)
            index += 1
            # Sleep until the next slot, accounting for scheduling drift.
            next_tick = t0 + index * interval
            sleep_for = next_tick - time.perf_counter()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

        summary.results     = list(await asyncio.gather(*all_tasks))
        summary.wall_time_s = time.perf_counter() - t0

    return summary


# ── Health-check ──────────────────────────────────────────────────────────────

async def health_check(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url}/health", timeout=5.0)
            return r.status_code == 200
    except Exception:
        return False


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(summaries: list[ScenarioSummary]) -> None:
    # ── Per-scenario latency & throughput table ───────────────────────────────
    perf_table = Table(title="Scenario Performance", show_lines=True)
    perf_table.add_column("Scenario",      style="bold cyan",  no_wrap=True)
    perf_table.add_column("Requests",      justify="right")
    perf_table.add_column("Success %",     justify="right")
    perf_table.add_column("Mean (s)",      justify="right")
    perf_table.add_column("p50 (s)",       justify="right")
    perf_table.add_column("p95 (s)",       justify="right")
    perf_table.add_column("p99 (s)",       justify="right")
    perf_table.add_column("Throughput",    justify="right")
    perf_table.add_column("Wall time (s)", justify="right")

    for s in summaries:
        ok = s.success_rate >= 95
        perf_table.add_row(
            s.name,
            str(s.total),
            f"[green]{s.success_rate:.1f}%[/green]" if ok else f"[red]{s.success_rate:.1f}%[/red]",
            f"{s.mean:.3f}",
            f"{s.p50:.3f}",
            f"{s.p95:.3f}",
            f"{s.p99:.3f}",
            f"{s.throughput:.2f} req/s",
            f"{s.wall_time_s:.2f}",
        )

    console.print(perf_table)

    # ── Per-scenario HTTP status breakdown ────────────────────────────────────
    status_table = Table(title="HTTP Status Breakdown", show_lines=True)
    status_table.add_column("Scenario", style="bold cyan", no_wrap=True)
    status_table.add_column("Status",   justify="right")
    status_table.add_column("Count",    justify="right")

    for s in summaries:
        for status, count in sorted(s.status_breakdown().items()):
            color = "green" if status == "200" else "red"
            status_table.add_row(
                s.name,
                f"[{color}]{status}[/{color}]",
                str(count),
            )

    console.print(status_table)

    # ── Individual failures ───────────────────────────────────────────────────
    failures = [
        (s.name, r)
        for s in summaries
        for r in s.results
        if not r.ok
    ]
    if failures:
        fail_table = Table(title="Failed Requests", show_lines=True)
        fail_table.add_column("Scenario", style="bold cyan")
        fail_table.add_column("#",        justify="right")
        fail_table.add_column("Status",   justify="right", style="red")
        fail_table.add_column("Error",    style="dim")

        for scenario_name, r in failures[:50]:   # cap at 50 rows
            fail_table.add_row(
                scenario_name,
                str(r.index),
                str(r.status),
                r.error or "",
            )
        if len(failures) > 50:
            fail_table.add_row("...", f"(+{len(failures) - 50} more)", "", "")
        console.print(fail_table)
    else:
        console.print("[bold green]✓ No failures.[/bold green]")


async def main() -> None:
    console.rule("[bold blue]Course Advisor API — Concurrency Test[/bold blue]")
    console.print(f"Target: [bold]{BASE_URL}[/bold]\n")

    console.print("Checking API health...", end=" ")
    if not await health_check(BASE_URL):
        console.print("[bold red]FAILED[/bold red] — is the server running?")
        return
    console.print("[bold green]OK[/bold green]\n")

    summaries: list[ScenarioSummary] = []

    if not SKIP_BURST:
        console.print(f"[bold]1/3 Burst[/bold] — {BURST_N} simultaneous requests")
        summary = await run_burst(BASE_URL, BURST_N, TIMEOUT)
        summaries.append(summary)
        console.print(f"  Done in {summary.wall_time_s:.2f}s  "
                      f"({summary.successes}/{summary.total} ok)\n")

    if not SKIP_RAMP:
        console.print(f"[bold]2/3 Ramp[/bold] — 1 → {RAMP_MAX} concurrent, step {RAMP_STEP}")
        summary = await run_ramp(BASE_URL, RAMP_MAX, RAMP_STEP, TIMEOUT)
        summaries.append(summary)
        console.print(f"  Done in {summary.wall_time_s:.2f}s  "
                      f"({summary.successes}/{summary.total} ok)\n")

    if not SKIP_SUSTAIN:
        console.print(f"[bold]3/3 Sustain[/bold] — {SUSTAIN_RPS} req/s for {SUSTAIN_DUR:.0f}s")
        summary = await run_sustain(BASE_URL, SUSTAIN_RPS, SUSTAIN_DUR, TIMEOUT)
        summaries.append(summary)
        console.print(f"  Done in {summary.wall_time_s:.2f}s  "
                      f"({summary.successes}/{summary.total} ok)\n")

    console.rule("Results")
    print_summary(summaries)


if __name__ == "__main__":
    asyncio.run(main())
