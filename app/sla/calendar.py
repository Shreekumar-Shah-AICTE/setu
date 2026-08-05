"""Business-hours calendar for SLA calculations.

Business hours are Mon–Sat 10:30–18:10 IST, excluding Sundays and the holidays
seeded in the ``holidays`` table. All public functions accept and return
timezone-aware UTC datetimes; the arithmetic is done in IST internally.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Holiday

IST = ZoneInfo("Asia/Kolkata")
OPEN_TIME = time(10, 30)
CLOSE_TIME = time(18, 10)
BUSINESS_MINUTES_PER_DAY = (18 * 60 + 10) - (10 * 60 + 30)  # 460


def load_holidays(db: Session) -> set[str]:
    return set(db.scalars(select(Holiday.date)))


def _to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def is_business_day(d, holidays: set[str]) -> bool:
    # Monday=0 .. Sunday=6. Sunday is closed.
    return d.weekday() != 6 and d.isoformat() not in holidays


def is_business_time(dt: datetime, holidays: set[str]) -> bool:
    ist = _to_ist(dt)
    if not is_business_day(ist.date(), holidays):
        return False
    return OPEN_TIME <= ist.time() < CLOSE_TIME


def _open_dt(d) -> datetime:
    return datetime.combine(d, OPEN_TIME, tzinfo=IST)


def _close_dt(d) -> datetime:
    return datetime.combine(d, CLOSE_TIME, tzinfo=IST)


def _next_business_open(dt_ist: datetime, holidays: set[str]) -> datetime:
    d = dt_ist.date()
    # If before open on a business day, snap to today's open.
    if is_business_day(d, holidays) and dt_ist < _open_dt(d):
        return _open_dt(d)
    # If within business hours, keep as-is.
    if is_business_day(d, holidays) and _open_dt(d) <= dt_ist < _close_dt(d):
        return dt_ist
    # Otherwise advance to the next business day's open.
    d = d + timedelta(days=1)
    while not is_business_day(d, holidays):
        d = d + timedelta(days=1)
    return _open_dt(d)


def add_business_hours(start_utc: datetime, hours: float, holidays: set[str]) -> datetime:
    """Add ``hours`` of business time to ``start_utc`` and return UTC."""
    remaining = timedelta(hours=hours)
    cur = _next_business_open(_to_ist(start_utc), holidays)
    while remaining.total_seconds() > 0:
        close = _close_dt(cur.date())
        available = close - cur
        if remaining <= available:
            cur = cur + remaining
            remaining = timedelta(0)
        else:
            remaining -= available
            # jump to next business day's open
            d = cur.date() + timedelta(days=1)
            while not is_business_day(d, holidays):
                d = d + timedelta(days=1)
            cur = _open_dt(d)
    return _to_utc(cur)
