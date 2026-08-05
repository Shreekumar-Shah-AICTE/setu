"""Duplicate detection.

On intake, cosine-compare the new embedding against grievances from the last 30
days in the same district. Above the (runtime-editable) threshold the new
grievance is marked DUPLICATE and linked to the original; the citizen is told
their issue is already tracked and no second officer email is sent.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.vectors import find_similar


@dataclass
class DuplicateMatch:
    grievance_id: str
    score: float


def check_duplicate(
    db: Session,
    embedding: list[float],
    *,
    district: str | None,
    threshold: float,
    exclude_id: str | None = None,
    within_days: int = 30,
) -> DuplicateMatch | None:
    matches = find_similar(
        db, embedding, district=district, within_days=within_days, exclude_id=exclude_id, top_k=1
    )
    if matches and matches[0][1] >= threshold:
        return DuplicateMatch(grievance_id=matches[0][0], score=matches[0][1])
    return None
