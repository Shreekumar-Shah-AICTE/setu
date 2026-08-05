"""SETU preflight — a connectivity and readiness checker.

Run it on-site before a demo/deployment:  python scripts/preflight.py

It prints a clear human-readable report and exits non-zero on a hard failure.
It loudly warns if the embedding dimensionality differs from 1024, since that
invalidates the cached centroids and requires a re-seed.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine, session_scope  # noqa: E402
from app.llm.catalogue import EMBEDDING_DIM, ARBITER_MODEL, EMBEDDING_MODEL  # noqa: E402
from app.llm.factory import get_llm_client  # noqa: E402
from app.models import Department, Officer  # noqa: E402

OK, WARN, FAIL = "✓", "!", "✗"


class Report:
    def __init__(self):
        self.passed = self.warned = self.failed = 0

    def line(self, mark: str, label: str, detail: str = ""):
        if mark == OK:
            self.passed += 1
        elif mark == WARN:
            self.warned += 1
        else:
            self.failed += 1
        print(f"[{mark}] {label:<28} {detail}")


async def run() -> int:
    settings = get_settings()
    r = Report()
    print("SETU PREFLIGHT")
    print("==============")

    r.line(OK, "Configuration loaded", f"provider={settings.llm_provider}  email={settings.email_provider}")

    # Database
    try:
        from sqlalchemy import inspect

        with session_scope() as db:
            n_dept = db.scalar(select(func.count()).select_from(Department)) or 0
            n_off = db.scalar(select(func.count()).select_from(Officer)) or 0
        tables = len(inspect(engine).get_table_names())
        mark = OK if (n_dept >= 11 and n_off >= 33) else WARN
        r.line(mark, "Database reachable", f"{tables} tables, {n_dept} departments, {n_off} officers")
    except Exception as exc:
        r.line(FAIL, "Database reachable", str(exc))

    client = get_llm_client()

    # Provider health
    try:
        started = time.perf_counter()
        health = await client.health()
        ms = (time.perf_counter() - started) * 1000
        if settings.llm_provider == "gateway":
            mark = OK if health.healthy else FAIL
            r.line(mark, "Gateway /health", f"{'reachable' if health.healthy else 'unreachable'} in {ms:.0f} ms")
            r.line(OK if health.models else WARN, "Gateway /v1/models", f"{len(health.models)} models")
            required = {EMBEDDING_MODEL, ARBITER_MODEL}
            present = required.issubset(set(health.models)) if health.models else False
            r.line(OK if present else WARN, "Required models present",
                   f"{EMBEDDING_MODEL}, {ARBITER_MODEL}" if present else "not confirmed")
        else:
            r.line(OK, f"Provider '{client.name}'", health.detail)
    except Exception as exc:
        r.line(FAIL, "Provider health", str(exc))

    # Embedding smoke test + dimensionality check
    try:
        vec = (await client.embed(model=EMBEDDING_MODEL, texts=["ગામમાં વીજ નથી"]))[0]
        import math

        norm = math.sqrt(sum(v * v for v in vec))
        dim = len(vec)
        r.line(OK, "Embedding smoke test", f"{dim} dims, norm {norm:.3f}")
        if dim != EMBEDDING_DIM:
            r.line(WARN, "Embedding dimensionality",
                   f"{dim} != {EMBEDDING_DIM} — cached centroids are INVALID; run `python -m app.cli seed` to re-fit")
    except Exception as exc:
        r.line(FAIL, "Embedding smoke test", str(exc))

    # Rerank note (custom endpoint; 404 expected on the gateway)
    if settings.llm_provider == "gateway":
        r.line(WARN, "Rerank endpoint", "custom /v1/rerank — 404 tolerated, cosine fallback active")

    # Arbiter JSON smoke test
    try:
        from app.classification.arbiter import run_arbiter

        started = time.perf_counter()
        result = await run_arbiter(
            client, grievance_text="ટ્રાન્સફોર્મર બળી ગયું અંધારપટ", language="gu",
            departments=[("ENERGY", "Energy", "ઊર્જા"), ("OTHER", "Other", "અન્ય")],
            lexical_hits=[], candidates=[("ENERGY", 0.5), ("OTHER", 0.1)],
        )
        ms = (time.perf_counter() - started) * 1000
        mark = OK if result.parsed is not None else WARN
        r.line(mark, "Arbiter JSON smoke test",
               f"valid schema in {ms/1000:.1f} s" if result.parsed else "fell back to fused winner")
    except Exception as exc:
        r.line(FAIL, "Arbiter JSON smoke test", str(exc))

    # Scheduler configuration
    r.line(OK if settings.scheduler_enabled else WARN, "Scheduler",
           f"enabled, sweeps every {settings.sla_sweep_seconds}s" if settings.scheduler_enabled else "disabled")

    print()
    print(f"{'READY' if r.failed == 0 else 'NOT READY'}. "
          f"{r.passed} passed, {r.warned} warning(s), {r.failed} failed.")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
