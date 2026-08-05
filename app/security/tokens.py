"""Signed, single-use officer action tokens (magic links).

Design:
* 32 bytes from ``secrets.token_urlsafe`` form the raw token that goes in the
  email URL.
* Only an HMAC-SHA256 of the raw token (keyed by ``SECRET_KEY``) is stored — the
  raw token never touches the database.
* Verification recomputes the HMAC and compares in constant time.
* Tokens are single-use (``used_at``) and expire at ``sla_due_at + 48h``.

State is never mutated on GET (email clients and scanners prefetch links); the
router only mutates on POST.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ActionToken

TOKEN_TTL_AFTER_SLA_HOURS = 48


def _hash_token(raw: str) -> str:
    secret = get_settings().secret_key.encode("utf-8")
    return hmac.new(secret, raw.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class IssuedToken:
    raw: str
    row: ActionToken
    url: str


def action_url(raw: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/action/{raw}"


def create_action_token(
    db: Session,
    *,
    grievance_id: str,
    officer_id: str,
    action: str,
    expires_at: datetime,
) -> IssuedToken:
    raw = secrets.token_urlsafe(32)
    row = ActionToken(
        grievance_id=grievance_id,
        officer_id=officer_id,
        action=action,
        token_hash=_hash_token(raw),
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return IssuedToken(raw=raw, row=row, url=action_url(raw))


def default_expiry(sla_due_at: datetime | None) -> datetime:
    base = sla_due_at or datetime.now(timezone.utc)
    return base + timedelta(hours=TOKEN_TTL_AFTER_SLA_HOURS)


@dataclass
class VerifiedToken:
    token: ActionToken
    valid: bool
    reason: str | None = None  # expired | used | invalid


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def verify_action_token(db: Session, raw: str) -> VerifiedToken:
    """Return the token row and whether it is currently usable. Does not mutate."""
    token_hash = _hash_token(raw)
    row = db.scalar(select(ActionToken).where(ActionToken.token_hash == token_hash))
    if row is None:
        return VerifiedToken(token=None, valid=False, reason="invalid")
    # Constant-time confirmation (defensive; the indexed lookup already matched).
    if not hmac.compare_digest(row.token_hash, token_hash):
        return VerifiedToken(token=None, valid=False, reason="invalid")
    now = datetime.now(timezone.utc)
    if row.used_at is not None:
        return VerifiedToken(token=row, valid=False, reason="used")
    if _aware(row.expires_at) is not None and now > _aware(row.expires_at):
        return VerifiedToken(token=row, valid=False, reason="expired")
    return VerifiedToken(token=row, valid=True)


def mark_used(db: Session, token: ActionToken) -> None:
    token.used_at = datetime.now(timezone.utc)
    db.flush()
