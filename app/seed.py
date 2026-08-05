"""Idempotent database seeding.

Loads departments + keywords, the officer directory, holidays, default SLA
policies and classification settings. Loads the golden evaluation set too if
``data/golden_set.jsonl`` is present (it is generated in the evaluation phase).

Re-running ``seed`` is safe: seed-sourced rows are refreshed while learned
keywords and admin-edited settings are preserved.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine, session_scope
from app.models import (
    Department,
    GoldenSample,
    Holiday,
    Keyword,
    Officer,
    SLAPolicy,
)
from app.runtime_config import seed_defaults

logger = logging.getLogger("setu.seed")

DEFAULT_SLA_HOURS = {"L1": 72.0, "L2": 48.0, "L3": 24.0}


def init_db() -> None:
    """Create all tables if they do not exist (safe to call repeatedly)."""
    Base.metadata.create_all(engine)


def _basic_normalize(term: str) -> str:
    """A minimal NFC + whitespace-collapse used to populate term_normalized.

    The authoritative folded matching form is produced by
    ``app.classification.normalize`` at automaton-build time from the raw term,
    so this value is informational only.
    """
    return " ".join(unicodedata.normalize("NFC", term).split())


def _data_path(name: str) -> Path:
    return get_settings().data_path / name


def seed_departments(db: Session) -> dict[str, Department]:
    doc = yaml.safe_load(_data_path("departments.yaml").read_text(encoding="utf-8"))
    code_to_dept: dict[str, Department] = {}
    for entry in doc["departments"]:
        code = entry["code"]
        dept = db.scalar(select(Department).where(Department.code == code))
        if dept is None:
            dept = Department(code=code)
            db.add(dept)
        dept.name_en = entry["name_en"]
        dept.name_gu = entry["name_gu"]
        dept.description = entry.get("description")
        dept.is_active = True
        db.flush()
        code_to_dept[code] = dept

        # Refresh seed keywords (preserve learned ones).
        existing_seed = db.scalars(
            select(Keyword).where(Keyword.department_id == dept.id, Keyword.source == "seed")
        ).all()
        for kw in existing_seed:
            db.delete(kw)
        db.flush()
        for term in entry.get("keywords", []) or []:
            db.add(
                Keyword(
                    department_id=dept.id,
                    term=term,
                    term_normalized=_basic_normalize(term),
                    token_count=len(term.split()),
                    weight=1.0,
                    source="seed",
                    is_active=True,
                )
            )
        db.flush()
    logger.info("Seeded %d departments", len(code_to_dept))
    return code_to_dept


def seed_officers(db: Session, code_to_dept: dict[str, Department]) -> int:
    doc = yaml.safe_load(_data_path("officers.seed.yaml").read_text(encoding="utf-8"))
    count = 0
    for entry in doc["officers"]:
        dept = code_to_dept.get(entry["department"])
        if dept is None:
            continue
        officer = db.scalar(select(Officer).where(Officer.email == entry["email"]))
        if officer is None:
            officer = Officer(email=entry["email"])
            db.add(officer)
        officer.department_id = dept.id
        officer.name = entry["name"]
        officer.designation_en = entry["designation_en"]
        officer.designation_gu = entry["designation_gu"]
        officer.phone = entry.get("phone")
        officer.level = entry["level"]
        officer.district = entry.get("district")
        officer.is_active = True
        count += 1
    db.flush()
    logger.info("Seeded %d officers", count)
    return count


def seed_holidays(db: Session) -> int:
    doc = yaml.safe_load(_data_path("holidays.yaml").read_text(encoding="utf-8"))
    count = 0
    for entry in doc["holidays"]:
        existing = db.scalar(select(Holiday).where(Holiday.date == entry["date"]))
        if existing is None:
            db.add(Holiday(date=entry["date"], name=entry["name"]))
            count += 1
        else:
            existing.name = entry["name"]
    db.flush()
    logger.info("Seeded %d holidays", count)
    return count


def seed_sla_policies(db: Session) -> None:
    for level, hours in DEFAULT_SLA_HOURS.items():
        existing = db.scalar(
            select(SLAPolicy).where(SLAPolicy.department_id.is_(None), SLAPolicy.level == level)
        )
        if existing is None:
            db.add(SLAPolicy(department_id=None, level=level, hours=hours, business_hours_only=True, is_active=True))
    db.flush()
    logger.info("Seeded global SLA policies")


def seed_golden_set(db: Session) -> int:
    path = _data_path("golden_set.jsonl")
    if not path.exists():
        logger.info("No golden_set.jsonl yet — skipping golden sample seed")
        return 0
    # Refresh golden samples entirely from the file (source of truth).
    for gs in db.scalars(select(GoldenSample)).all():
        db.delete(gs)
    db.flush()
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        db.add(
            GoldenSample(
                text=obj["text"],
                expected_department_code=obj["expected_department_code"],
                expected_secondary=obj.get("expected_secondary", []),
                language=obj.get("language"),
                tags=obj.get("tags", []),
                split=obj.get("split", "test"),
                notes=obj.get("notes"),
            )
        )
        count += 1
    db.flush()
    logger.info("Seeded %d golden samples", count)
    return count


def seed_all(db: Session) -> dict:
    """Run the full seed within an existing session. Returns a small summary."""
    code_to_dept = seed_departments(db)
    officers = seed_officers(db, code_to_dept)
    holidays = seed_holidays(db)
    seed_sla_policies(db)
    seed_defaults(db)
    golden = seed_golden_set(db)
    return {
        "departments": len(code_to_dept),
        "officers": officers,
        "holidays": holidays,
        "golden_samples": golden,
    }


def run_seed(compute_centroids_after: bool = True) -> dict:
    """Entry point used by the CLI: ensure schema, seed, then fit centroids."""
    init_db()
    with session_scope() as db:
        summary = seed_all(db)
    if compute_centroids_after:
        import asyncio

        from app.classification.semantic import compute_centroids
        from app.llm.factory import get_llm_client

        with session_scope() as db:
            asyncio.run(compute_centroids(db, get_llm_client()))
    logger.info("Seed complete: %s", summary)
    return summary
