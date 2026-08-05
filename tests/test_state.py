"""Tests for the grievance state machine (app/state.py)."""
from __future__ import annotations

import uuid

import pytest

from app.models import Grievance, GrievanceEvent
from app.state import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    Status,
    can_transition,
    record_event,
    transition,
)


def _new_grievance(db, status=Status.RECEIVED) -> Grievance:
    g = Grievance(
        ref_no=f"SETU-TEST-{uuid.uuid4().hex[:8]}",
        citizen_name="Test Citizen",
        subject="s",
        body_raw="b",
        status=status.value,
    )
    db.add(g)
    db.flush()
    return g


def test_allowed_transitions_cover_all_statuses():
    # Every Status is a key in the transition table.
    for status in Status:
        assert status in ALLOWED_TRANSITIONS


def test_legal_transition_writes_event(db):
    g = _new_grievance(db, Status.RECEIVED)
    ev = transition(db, g, Status.CLASSIFIED, event_type="classified")
    assert g.status == Status.CLASSIFIED.value
    assert isinstance(ev, GrievanceEvent)
    assert ev.from_status == "RECEIVED"
    assert ev.to_status == "CLASSIFIED"


def test_illegal_transition_raises(db):
    g = _new_grievance(db, Status.RECEIVED)
    with pytest.raises(InvalidTransitionError):
        transition(db, g, Status.RESOLVED)  # not reachable directly from RECEIVED


def test_full_happy_path(db):
    g = _new_grievance(db, Status.RECEIVED)
    transition(db, g, Status.CLASSIFIED)
    transition(db, g, Status.ASSIGNED_L1)
    assert g.current_level == "L1"
    assert g.assigned_at is not None
    transition(db, g, Status.ACKNOWLEDGED_L1)
    transition(db, g, Status.ESCALATED_L2)
    assert g.current_level == "L2"
    transition(db, g, Status.RESOLVED)
    assert g.resolved_at is not None
    transition(db, g, Status.CLOSED)
    assert g.closed_at is not None


def test_critical_skips_l1(db):
    g = _new_grievance(db, Status.RECEIVED)
    transition(db, g, Status.CLASSIFIED)
    # CRITICAL grievance goes straight to L2.
    transition(db, g, Status.ESCALATED_L2)
    assert g.current_level == "L2"


def test_reopen_clears_resolution_timestamps(db):
    g = _new_grievance(db, Status.RESOLVED)
    g.resolved_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    db.flush()
    transition(db, g, Status.REOPENED)
    assert g.resolved_at is None
    assert g.closed_at is None
    # A reopened grievance can be pushed back into the workflow.
    transition(db, g, Status.ASSIGNED_L1)


def test_terminal_states_have_no_exits():
    assert ALLOWED_TRANSITIONS[Status.DUPLICATE] == set()
    assert ALLOWED_TRANSITIONS[Status.REJECTED] == set()


def test_can_transition_helper():
    assert can_transition("RECEIVED", "CLASSIFIED") is True
    assert can_transition("RECEIVED", "RESOLVED") is False
    assert can_transition(Status.RESOLVED, Status.REOPENED) is True


def test_record_event_does_not_change_status(db):
    g = _new_grievance(db, Status.ASSIGNED_L1)
    ev = record_event(db, g, "sla_paused", note="awaiting citizen")
    assert g.status == Status.ASSIGNED_L1.value
    assert ev.from_status == ev.to_status == "ASSIGNED_L1"
    assert ev.event_type == "sla_paused"
