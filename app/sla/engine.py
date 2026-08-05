"""SLA engine — compute deadlines and level transitions.

The deadline is computed at assignment time and stored on ``sla_due_at`` so it
never silently moves. ``SLA_TIME_SCALE`` divides all durations (set it to 3600
to make 72 hours elapse in 72 seconds for a live escalation demo).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.urgency import CRITICAL_SLA_HOURS, URGENCY_SLA_FACTOR
from app.config import get_settings
from app.models import Grievance, SLAPolicy
from app.sla.calendar import add_business_hours, load_holidays
from app.state import Status

logger = logging.getLogger("setu.sla")

LEVEL_ORDER = ["L1", "L2", "L3"]

# States from which the SLA sweeper may escalate on breach.
ESCALATABLE_STATUSES = {
    Status.ASSIGNED_L1.value, Status.ACKNOWLEDGED_L1.value,
    Status.ESCALATED_L2.value, Status.ACKNOWLEDGED_L2.value,
    Status.ESCALATED_L3.value,
}


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


def _already_escalated_to(grievance: Grievance, to_level: str) -> bool:
    """Idempotency guard: has this grievance already been escalated to to_level?"""
    for ev in grievance.events:
        if ev.event_type == "escalated" and (ev.payload or {}).get("to_level") == to_level:
            return True
    return False


async def run_sla_sweep(db: Session, provider=None, *, now: datetime | None = None) -> list[dict]:
    """Find breached grievances in non-terminal states and escalate them.

    Escalation writes are guarded by a uniqueness check on (grievance_id,
    to_level) plus a status precondition, so a job that runs twice cannot
    double-escalate.
    """
    from app.routing.dispatcher import escalate_grievance  # lazy import (avoids cycle)
    from app.state import ActorType

    now = now or datetime.now(timezone.utc)
    stmt = select(Grievance).where(
        Grievance.sla_due_at.is_not(None),
        Grievance.sla_due_at <= now,
        Grievance.status.in_(ESCALATABLE_STATUSES),
    )
    actions: list[dict] = []
    for grievance in db.scalars(stmt):
        current = grievance.current_level or "L1"
        to_level = next_level(current)

        if to_level is None:
            # L3 breach — alert once, then stop it re-firing by clearing the due date.
            await escalate_grievance(
                db, grievance, to_level=None, reason="L3 SLA breached",
                actor_type=ActorType.SYSTEM, actor_label="SLA sweeper", provider=provider,
            )
            grievance.sla_due_at = None
            actions.append({"ref_no": grievance.ref_no, "action": "l3_alert"})
            continue

        if _already_escalated_to(grievance, to_level):
            continue  # uniqueness guard

        await escalate_grievance(
            db, grievance, to_level=to_level, reason=f"SLA breach at {current}",
            actor_type=ActorType.SYSTEM, actor_label="SLA sweeper", provider=provider,
        )
        actions.append({"ref_no": grievance.ref_no, "action": f"escalated_to_{to_level}"})

    if actions:
        logger.info("SLA sweep escalated %d grievance(s): %s", len(actions), actions)
    return actions
