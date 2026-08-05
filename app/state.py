"""The grievance lifecycle state machine.

There is exactly **one** code path that writes ``grievances.status``: the
:func:`transition` function below. Every transition is validated against
:data:`ALLOWED_TRANSITIONS` and every transition appends a row to the
append-only ``grievance_events`` table. Illegal transitions raise
:class:`InvalidTransitionError`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Grievance, GrievanceEvent


class Status(str, Enum):
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ASSIGNED_L1 = "ASSIGNED_L1"
    ACKNOWLEDGED_L1 = "ACKNOWLEDGED_L1"
    ESCALATED_L2 = "ESCALATED_L2"
    ACKNOWLEDGED_L2 = "ACKNOWLEDGED_L2"
    ESCALATED_L3 = "ESCALATED_L3"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class Urgency(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class Level(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ActorType(str, Enum):
    SYSTEM = "system"
    OFFICER = "officer"
    CITIZEN = "citizen"
    ADMIN = "admin"


class InvalidTransitionError(Exception):
    """Raised when a status change is not permitted by the state machine."""


# The permitted transitions. Read this alongside the diagram in the spec §5.
ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.RECEIVED: {Status.CLASSIFIED, Status.NEEDS_REVIEW, Status.DUPLICATE, Status.REJECTED},
    # CRITICAL grievances skip L1 and go straight to L2 (ESCALATED_L2).
    Status.CLASSIFIED: {Status.ASSIGNED_L1, Status.ESCALATED_L2, Status.NEEDS_REVIEW, Status.DUPLICATE, Status.REJECTED},
    # A human reviewer corrects and pushes back into the workflow.
    Status.NEEDS_REVIEW: {Status.CLASSIFIED, Status.ASSIGNED_L1, Status.ESCALATED_L2, Status.DUPLICATE, Status.REJECTED},
    Status.ASSIGNED_L1: {Status.ACKNOWLEDGED_L1, Status.ESCALATED_L2, Status.RESOLVED, Status.REJECTED},
    Status.ACKNOWLEDGED_L1: {Status.ESCALATED_L2, Status.RESOLVED, Status.REJECTED},
    Status.ESCALATED_L2: {Status.ACKNOWLEDGED_L2, Status.ESCALATED_L3, Status.RESOLVED, Status.REJECTED},
    Status.ACKNOWLEDGED_L2: {Status.ESCALATED_L3, Status.RESOLVED, Status.REJECTED},
    Status.ESCALATED_L3: {Status.RESOLVED, Status.REJECTED},
    Status.RESOLVED: {Status.CLOSED, Status.REOPENED},
    Status.CLOSED: {Status.REOPENED},
    Status.REOPENED: {Status.CLASSIFIED, Status.ASSIGNED_L1, Status.ESCALATED_L2},
    Status.DUPLICATE: set(),
    Status.REJECTED: set(),
}

# Statuses at which the SLA sweeper should never act.
TERMINAL_STATUSES: set[Status] = {Status.RESOLVED, Status.CLOSED, Status.DUPLICATE, Status.REJECTED}

# Which level a status represents (used to set grievance.current_level).
_STATUS_LEVEL: dict[Status, str] = {
    Status.ASSIGNED_L1: Level.L1.value,
    Status.ACKNOWLEDGED_L1: Level.L1.value,
    Status.ESCALATED_L2: Level.L2.value,
    Status.ACKNOWLEDGED_L2: Level.L2.value,
    Status.ESCALATED_L3: Level.L3.value,
}


def _coerce(status: "str | Status") -> Status:
    return status if isinstance(status, Status) else Status(status)


def can_transition(from_status: "str | Status", to_status: "str | Status") -> bool:
    return _coerce(to_status) in ALLOWED_TRANSITIONS.get(_coerce(from_status), set())


def transition(
    db: Session,
    grievance: Grievance,
    to_status: "str | Status",
    *,
    event_type: Optional[str] = None,
    actor_type: "str | ActorType" = ActorType.SYSTEM,
    actor_id: Optional[str] = None,
    actor_label: Optional[str] = None,
    note: Optional[str] = None,
    payload: Optional[dict] = None,
) -> GrievanceEvent:
    """Validate and apply a status transition, recording an audit event.

    Does not commit — the caller owns the transaction. Raises
    :class:`InvalidTransitionError` on an illegal transition.
    """
    from_status = _coerce(grievance.status)
    target = _coerce(to_status)

    if target not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise InvalidTransitionError(
            f"Illegal transition {from_status.value} -> {target.value} "
            f"for grievance {grievance.ref_no or grievance.id}"
        )

    now = datetime.now(timezone.utc)
    grievance.status = target.value
    grievance.updated_at = now

    # Maintain current_level for the states that carry one.
    if target in _STATUS_LEVEL:
        grievance.current_level = _STATUS_LEVEL[target]

    # Coherent timestamp bookkeeping.
    if target in (Status.ASSIGNED_L1, Status.ESCALATED_L2) and grievance.assigned_at is None:
        grievance.assigned_at = now
    if target == Status.RESOLVED:
        grievance.resolved_at = now
    if target == Status.CLOSED:
        grievance.closed_at = now
    if target == Status.REOPENED:
        # A reopen clears the resolution timestamps so the clock restarts cleanly.
        grievance.resolved_at = None
        grievance.closed_at = None

    actor_type_value = actor_type.value if isinstance(actor_type, ActorType) else str(actor_type)
    event = GrievanceEvent(
        grievance_id=grievance.id,
        event_type=event_type or f"transition:{target.value}",
        from_status=from_status.value,
        to_status=target.value,
        actor_type=actor_type_value,
        actor_id=actor_id,
        actor_label=actor_label,
        note=note,
        payload=payload,
        created_at=now,
    )
    db.add(event)
    db.flush()
    return event


def record_event(
    db: Session,
    grievance: Grievance,
    event_type: str,
    *,
    actor_type: "str | ActorType" = ActorType.SYSTEM,
    actor_id: Optional[str] = None,
    actor_label: Optional[str] = None,
    note: Optional[str] = None,
    payload: Optional[dict] = None,
) -> GrievanceEvent:
    """Append a non-transition audit event (e.g. email sent, SLA paused)."""
    actor_type_value = actor_type.value if isinstance(actor_type, ActorType) else str(actor_type)
    event = GrievanceEvent(
        grievance_id=grievance.id,
        event_type=event_type,
        from_status=grievance.status,
        to_status=grievance.status,
        actor_type=actor_type_value,
        actor_id=actor_id,
        actor_label=actor_label,
        note=note,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
    return event
