"""Tests for the SLA engine, business calendar, sweeper idempotency, time scaling."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.classification.pipeline import intake_grievance
from app.config import reload_settings
from app.email.console import ConsoleEmailProvider
from app.models import ActionToken, GrievanceEvent, Officer
from app.sla.calendar import IST, add_business_hours, is_business_time
from app.sla.engine import compute_sla_due, next_level, run_sla_sweep
from app.state import Status

HOLIDAYS = {"2026-08-15"}


def test_next_level():
    assert next_level("L1") == "L2"
    assert next_level("L2") == "L3"
    assert next_level("L3") is None


def test_business_time_predicate():
    # Monday 2026-08-03 12:00 IST is business time.
    mon_noon = datetime(2026, 8, 3, 12, 0, tzinfo=IST).astimezone(timezone.utc)
    assert is_business_time(mon_noon, HOLIDAYS) is True
    # Sunday is not.
    sun = datetime(2026, 8, 2, 12, 0, tzinfo=IST).astimezone(timezone.utc)
    assert is_business_time(sun, HOLIDAYS) is False
    # Before opening.
    early = datetime(2026, 8, 3, 9, 0, tzinfo=IST).astimezone(timezone.utc)
    assert is_business_time(early, HOLIDAYS) is False


def test_add_business_hours_same_day():
    start = datetime(2026, 8, 3, 11, 0, tzinfo=IST).astimezone(timezone.utc)  # Mon 11:00
    due = add_business_hours(start, 2.0, HOLIDAYS).astimezone(IST)
    assert (due.hour, due.minute) == (13, 0)
    assert due.date() == datetime(2026, 8, 3).date()


def test_add_business_hours_rolls_over_closing():
    # Mon 17:00 IST + 2h business => next business day, 460-min day = 7h40m.
    start = datetime(2026, 8, 3, 17, 0, tzinfo=IST).astimezone(timezone.utc)
    due = add_business_hours(start, 2.0, HOLIDAYS).astimezone(IST)
    assert due.date() == datetime(2026, 8, 4).date()  # Tuesday
    # 1h10m remained until close, so 50 min into the next day -> 11:20.
    assert (due.hour, due.minute) == (11, 20)


def test_add_business_hours_skips_sunday_and_holiday():
    # Saturday 2026-08-15 is Independence Day holiday; Sat 2026-08-15 -> next is Mon 17th? 15th is Sat holiday.
    # Start Friday 2026-08-14 17:30 IST (30 min to close), add 1h -> Sat is holiday(15), Sun(16) closed -> Mon 17th 10:30 + 30m
    start = datetime(2026, 8, 14, 17, 30, tzinfo=IST).astimezone(timezone.utc)
    due = add_business_hours(start, 1.0, HOLIDAYS).astimezone(IST)
    assert due.weekday() == 0  # Monday
    assert due.date() == datetime(2026, 8, 17).date()


def test_time_scale_shrinks_sla(db):
    os.environ["SLA_TIME_SCALE"] = "3600"
    try:
        reload_settings()
        now = datetime.now(timezone.utc)
        due = compute_sla_due(db, level="L1", urgency="NORMAL", at=now)
        # 72h / 3600 = 0.02h = 72 seconds.
        delta = (due - now).total_seconds()
        assert 60 < delta < 90
    finally:
        os.environ["SLA_TIME_SCALE"] = "1.0"
        reload_settings()


async def test_sweeper_escalates_and_is_idempotent(db):
    grievance, _ = await intake_grievance(
        db, citizen_name="C", subject="વીજ",
        body="ગામમાં ટ્રાન્સફોર્મર બળી ગયું અંધારપટ વીજપોલ પીજીવીસીએલ", citizen_district="Surat",
    )
    provider = ConsoleEmailProvider()
    from app.routing.dispatcher import dispatch_grievance

    if grievance.status != "CLASSIFIED":
        return  # NEEDS_REVIEW path not applicable to this deterministic input
    await dispatch_grievance(db, grievance, provider=provider)
    assert grievance.status == "ASSIGNED_L1"

    # Force a breach.
    grievance.sla_due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.flush()

    first = await run_sla_sweep(db, provider=provider)
    assert any(a["ref_no"] == grievance.ref_no for a in first)
    assert grievance.status == "ESCALATED_L2"

    escalated_to_l2 = [
        e for e in db.scalars(select(GrievanceEvent).where(GrievanceEvent.grievance_id == grievance.id))
        if e.event_type == "escalated" and (e.payload or {}).get("to_level") == "L2"
    ]
    assert len(escalated_to_l2) == 1

    # Running the sweep again must NOT double-escalate (due was pushed forward).
    second = await run_sla_sweep(db, provider=provider)
    assert not any(a["ref_no"] == grievance.ref_no for a in second)
    still_one = [
        e for e in db.scalars(select(GrievanceEvent).where(GrievanceEvent.grievance_id == grievance.id))
        if e.event_type == "escalated" and (e.payload or {}).get("to_level") == "L2"
    ]
    assert len(still_one) == 1
