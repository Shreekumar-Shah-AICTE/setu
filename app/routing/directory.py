"""Officer directory lookup."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Officer


def select_officer(
    db: Session, department_id: str, level: str, district: str | None = None
) -> Officer | None:
    """Pick an active officer for a department + level, preferring a district match."""
    base = select(Officer).where(
        Officer.department_id == department_id,
        Officer.level == level,
        Officer.is_active.is_(True),
    )
    if district:
        officer = db.scalar(base.where(Officer.district == district))
        if officer:
            return officer
    return db.scalar(base)


def officers_for_department(db: Session, department_id: str) -> list[Officer]:
    return list(
        db.scalars(
            select(Officer).where(Officer.department_id == department_id).order_by(Officer.level)
        )
    )
