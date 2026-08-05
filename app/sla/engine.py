"""SLA engine — compute deadlines and level transitions.

The deadline is computed at assignment time and stored on ``sla_due_at`` so it
never silently moves. ``SLA_TIME_SCALE`` divides all durations (set it to 3600
to make 72 hours elapse in 72 seconds for a live escalation demo).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.urgency import CRITICAL_SLA_HOURS, URGENCY_SLA_FACTOR
from app.config import get_settings
from app.models import SLAPolicy
from app.sla.calendar import add_business_hours, load_holidays

LEVEL_ORDER = ["L1", "L2", "L3"]


def next_level(level: str) -> str | None:
    try:
        idx = LEVEL_ORDER.index(level)
    except ValueError:
        return None
    return LEVEL_ORDER[idx + 1] if idx + 1 < len(LEVEL_ORDER) else None


def target_level_for_urgency(urgency: str) -> str:
    # CRITICAL skips L1 and is assigned directly to L2.
    return "L2" if urgency == "CRITICAL" else "L1"


def get_policy(db: Session, level: str, department_id: str | None = None) -> SLAPolicy | None:
    if department_id:
        policy = db.scalar(
            select(SLAPolicy).where(
                SLAPolicy.level == level, SLAPolicy.department_id == department_id,
                SLAPolicy.is_active.is_(True),
            )
        )
        if policy:
            return policy
    return db.scalar(
        select(SLAPolicy).where(
            SLAPolicy.level == level, SLAPolicy.department_id.is_(None), SLAPolicy.is_active.is_(True)
        )
    )


def base_hours_for(db: Session, level: str, department_id: str | None = None) -> tuple[float, bool]:
    policy = get_policy(db, level, department_id)
    if policy is None:
        defaults = {"L1": 72.0, "L2": 48.0, "L3": 24.0}
        return defaults.get(level, 48.0), True
    return policy.hours, policy.business_hours_only


def compute_sla_due(
    db: Session,
    *,
    level: str,
    urgency: str,
    department_id: str | None = None,
    at: datetime | None = None,
) -> datetime:
    at = at or datetime.now(timezone.utc)
    base_hours, business_only = base_hours_for(db, level, department_id)

    if urgency == "CRITICAL":
        hours = CRITICAL_SLA_HOURS
    else:
        hours = base_hours * URGENCY_SLA_FACTOR.get(urgency, 1.0)

    time_scale = max(get_settings().sla_time_scale, 1e-9)
    effective_hours = hours / time_scale

    # Business-hours arithmetic only makes sense at real time scale. When the
    # clock is accelerated for a demo, or the policy is 24/7, use wall-clock.
    if business_only and abs(time_scale - 1.0) < 1e-9:
        holidays = load_holidays(db)
        return add_business_hours(at, effective_hours, holidays)
    return at + timedelta(hours=effective_hours)
