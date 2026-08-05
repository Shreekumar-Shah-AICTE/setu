"""Tests for magic-link action tokens."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.main import app
from app.models import ActionToken, Grievance, Officer
from app.security.tokens import (
    create_action_token,
    default_expiry,
    mark_used,
    verify_action_token,
)


def _make_grievance(db) -> Grievance:
    officer = db.scalar(select(Officer))
    g = Grievance(ref_no=f"SETU-TOK-{datetime.now().timestamp():.0f}", citizen_name="T",
                  subject="s", body_raw="b", status="ASSIGNED_L1", assigned_officer_id=officer.id,
                  department_id=officer.department_id)
    db.add(g)
    db.flush()
    return g, officer


def test_token_roundtrip_valid(db):
    g, officer = _make_grievance(db)
    issued = create_action_token(db, grievance_id=g.id, officer_id=officer.id, action="resolve",
                                 expires_at=default_expiry(datetime.now(timezone.utc)))
    v = verify_action_token(db, issued.raw)
    assert v.valid is True
    assert v.token.action == "resolve"
    assert issued.url.endswith(issued.raw)


def test_only_hash_stored_not_raw(db):
    g, officer = _make_grievance(db)
    issued = create_action_token(db, grievance_id=g.id, officer_id=officer.id, action="info",
                                 expires_at=default_expiry(None))
    assert issued.raw not in issued.row.token_hash
    assert len(issued.row.token_hash) == 64  # sha256 hex


def test_tampered_token_is_invalid(db):
    g, officer = _make_grievance(db)
    issued = create_action_token(db, grievance_id=g.id, officer_id=officer.id, action="resolve",
                                 expires_at=default_expiry(None))
    v = verify_action_token(db, issued.raw + "x")
    assert v.valid is False
    assert v.reason == "invalid"


def test_expired_token(db):
    g, officer = _make_grievance(db)
    issued = create_action_token(db, grievance_id=g.id, officer_id=officer.id, action="resolve",
                                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    v = verify_action_token(db, issued.raw)
    assert v.valid is False and v.reason == "expired"


def test_single_use(db):
    g, officer = _make_grievance(db)
    issued = create_action_token(db, grievance_id=g.id, officer_id=officer.id, action="resolve",
                                 expires_at=default_expiry(None))
    mark_used(db, issued.row)
    v = verify_action_token(db, issued.raw)
    assert v.valid is False and v.reason == "used"


def test_get_action_does_not_mutate():
    # Create a committed grievance + token, then GET the link and confirm it is
    # still unused (GET must never mutate state).
    with session_scope() as db:
        officer = db.scalar(select(Officer))
        g = Grievance(ref_no=f"SETU-GET-{datetime.now().timestamp():.0f}", citizen_name="T",
                      subject="વીજ", body_raw="ગામમાં વીજ નથી", status="ASSIGNED_L1",
                      assigned_officer_id=officer.id, department_id=officer.department_id)
        db.add(g)
        db.flush()
        issued = create_action_token(db, grievance_id=g.id, officer_id=officer.id, action="resolve",
                                     expires_at=default_expiry(datetime.now(timezone.utc)))
        raw = issued.raw
        token_hash = issued.row.token_hash

    with TestClient(app) as client:
        resp = client.get(f"/action/{raw}")
    assert resp.status_code == 200
    assert "Confirm" in resp.text or "નિરાકરણ" in resp.text

    with session_scope() as db:
        row = db.scalar(select(ActionToken).where(ActionToken.token_hash == token_hash))
        assert row.used_at is None  # GET did not mutate
