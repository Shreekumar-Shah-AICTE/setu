"""SQLAlchemy 2.0 typed ORM models — the 13 tables of SETU.

UUID string primary keys throughout. JSON columns work identically on SQLite
and PostgreSQL. Timestamps are timezone-aware UTC.

``grievance_events`` and (by convention) ``classification_traces`` are
append-only audit records — rows are never updated or deleted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name_en: Mapped[str] = mapped_column(String(128))
    name_gu: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # L2-normalised centroid vector (list[float]) or None for OTHER.
    centroid: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    centroid_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    keywords: Mapped[list["Keyword"]] = relationship(back_populates="department", cascade="all, delete-orphan")
    officers: Mapped[list["Officer"]] = relationship(back_populates="department", cascade="all, delete-orphan")


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    term: Mapped[str] = mapped_column(String(256))            # raw, exactly as seeded
    term_normalized: Mapped[str] = mapped_column(String(256), index=True)  # folded form
    token_count: Mapped[int] = mapped_column(Integer, default=1)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(16), default="seed")  # seed | learned
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    department: Mapped["Department"] = relationship(back_populates="keywords")


class Officer(Base):
    __tablename__ = "officers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    designation_en: Mapped[str] = mapped_column(String(128))
    designation_gu: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(256))
    phone: Mapped[Optional[str]] = mapped_column(String(32), default=None)
    level: Mapped[str] = mapped_column(String(4))  # L1 | L2 | L3
    district: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department: Mapped["Department"] = relationship(back_populates="officers")


class Grievance(Base):
    __tablename__ = "grievances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ref_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    citizen_name: Mapped[str] = mapped_column(String(128))
    citizen_email: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    citizen_phone: Mapped[Optional[str]] = mapped_column(String(32), default=None)
    citizen_district: Mapped[Optional[str]] = mapped_column(String(64), default=None, index=True)

    subject: Mapped[str] = mapped_column(String(256))
    body_raw: Mapped[str] = mapped_column(Text)
    body_normalized: Mapped[Optional[str]] = mapped_column(Text, default=None)
    detected_language: Mapped[Optional[str]] = mapped_column(String(8), default=None)  # gu|en|gu-latn|mixed

    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"), default=None, index=True)
    secondary_department_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    urgency: Mapped[str] = mapped_column(String(16), default="NORMAL")  # CRITICAL|HIGH|NORMAL|LOW
    status: Mapped[str] = mapped_column(String(24), default="RECEIVED", index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    decided_by_stage: Mapped[Optional[int]] = mapped_column(Integer, default=None)  # 1..4
    current_level: Mapped[Optional[str]] = mapped_column(String(4), default=None)   # L1|L2|L3

    assigned_officer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("officers.id"), default=None)
    sla_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None, index=True)
    root_message_id: Mapped[Optional[str]] = mapped_column(String(256), default=None)

    embedding: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    duplicate_of_id: Mapped[Optional[str]] = mapped_column(ForeignKey("grievances.id"), default=None)

    resolution_note: Mapped[Optional[str]] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)

    department: Mapped[Optional["Department"]] = relationship(foreign_keys=[department_id])
    assigned_officer: Mapped[Optional["Officer"]] = relationship(foreign_keys=[assigned_officer_id])
    duplicate_of: Mapped[Optional["Grievance"]] = relationship(remote_side=[id], foreign_keys=[duplicate_of_id])
    events: Mapped[list["GrievanceEvent"]] = relationship(
        back_populates="grievance", cascade="all, delete-orphan", order_by="GrievanceEvent.created_at"
    )
    trace: Mapped[Optional["ClassificationTrace"]] = relationship(
        back_populates="grievance", cascade="all, delete-orphan", uselist=False
    )


class GrievanceEvent(Base):
    """Append-only audit log. Never UPDATE or DELETE a row here."""

    __tablename__ = "grievance_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    grievance_id: Mapped[str] = mapped_column(ForeignKey("grievances.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    from_status: Mapped[Optional[str]] = mapped_column(String(24), default=None)
    to_status: Mapped[Optional[str]] = mapped_column(String(24), default=None)
    actor_type: Mapped[str] = mapped_column(String(16), default="system")  # system|officer|citizen|admin
    actor_id: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    actor_label: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    note: Mapped[Optional[str]] = mapped_column(Text, default=None)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    grievance: Mapped["Grievance"] = relationship(back_populates="events")


class ClassificationTrace(Base):
    """The explainability record backing the admin Decision Trace panel."""

    __tablename__ = "classification_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    grievance_id: Mapped[str] = mapped_column(ForeignKey("grievances.id"), index=True, unique=True)
    normalized_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    lexical_scores: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    lexical_hits: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    semantic_scores: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    fused_scores: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    arbiter_invoked: Mapped[bool] = mapped_column(Boolean, default=False)
    arbiter_raw: Mapped[Optional[str]] = mapped_column(Text, default=None)
    arbiter_parsed: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    chosen_department_code: Mapped[Optional[str]] = mapped_column(String(32), default=None)
    confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)
    margin: Mapped[Optional[float]] = mapped_column(Float, default=None)
    decided_by_stage: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[Optional[str]] = mapped_column(String(16), default=None)  # mock|gateway|local
    latency_ms: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    grievance: Mapped["Grievance"] = relationship(back_populates="trace")


class ActionToken(Base):
    __tablename__ = "action_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    grievance_id: Mapped[str] = mapped_column(ForeignKey("grievances.id"), index=True)
    officer_id: Mapped[str] = mapped_column(ForeignKey("officers.id"))
    action: Mapped[str] = mapped_column(String(16))  # resolve | escalate | info
    token_hash: Mapped[str] = mapped_column(String(64), index=True)  # SHA-256 hex; raw token never stored
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"), default=None)  # None = global default
    level: Mapped[str] = mapped_column(String(4))  # L1|L2|L3
    hours: Mapped[float] = mapped_column(Float)
    business_hours_only: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    grievance_id: Mapped[str] = mapped_column(ForeignKey("grievances.id"), index=True)
    reason: Mapped[str] = mapped_column(String(32))  # low_confidence|narrow_margin|multi_department|other_bucket
    suggested_department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"), default=None)
    corrected_department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"), default=None)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GoldenSample(Base):
    __tablename__ = "golden_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    text: Mapped[str] = mapped_column(Text)
    expected_department_code: Mapped[str] = mapped_column(String(32), index=True)
    expected_secondary: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    language: Mapped[Optional[str]] = mapped_column(String(8), default=None)
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    split: Mapped[str] = mapped_column(String(8), default="test")  # dev | test
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_name: Mapped[str] = mapped_column(String(128))
    config: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    accuracy: Mapped[Optional[float]] = mapped_column(Float, default=None)
    macro_f1: Mapped[Optional[float]] = mapped_column(Float, default=None)
    weighted_f1: Mapped[Optional[float]] = mapped_column(Float, default=None)
    per_class: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    confusion_matrix: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    sample_count: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    date: Mapped[str] = mapped_column(String(10), unique=True, index=True)  # YYYY-MM-DD
    name: Mapped[str] = mapped_column(String(128))


class AppSetting(Base):
    """Runtime-editable configuration. Changing a value takes effect without a restart."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)  # always stored as {"value": <x>} wrapper
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


__all__ = [
    "Department",
    "Keyword",
    "Officer",
    "Grievance",
    "GrievanceEvent",
    "ClassificationTrace",
    "ActionToken",
    "SLAPolicy",
    "ReviewQueue",
    "GoldenSample",
    "EvalRun",
    "Holiday",
    "AppSetting",
]
