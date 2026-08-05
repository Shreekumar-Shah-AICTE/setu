"""APScheduler-based SLA sweeper.

An AsyncIOScheduler runs the escalation sweep every ``SLA_SWEEP_SECONDS`` (60s
by default) and once shortly after startup, so a breached grievance escalates
within about a minute of the server coming up. Combined with
``SLA_TIME_SCALE=3600`` this makes a 72-hour SLA elapse in 72 seconds for a live
demo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings

logger = logging.getLogger("setu.scheduler")


async def sweep_job() -> None:
    from app.db import session_scope
    from app.sla.engine import run_sla_sweep

    try:
        with session_scope() as db:
            await run_sla_sweep(db)
    except Exception as exc:  # never let a sweep error kill the scheduler
        logger.exception("SLA sweep failed: %s", exc)


def start_scheduler(app=None) -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sweep_job,
        "interval",
        seconds=settings.sla_sweep_seconds,
        id="sla_sweep",
        max_instances=1,
        coalesce=True,
        # First run a few seconds after startup so demo escalations fire promptly.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
    )
    scheduler.start()
    return scheduler
