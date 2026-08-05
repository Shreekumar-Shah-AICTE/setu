"""Runtime-editable configuration backed by the ``app_settings`` table.

The classification gating constants (alpha/fusion weight, confidence, margin,
other-threshold, review-threshold, semantic temperature, dedupe threshold) are
stored in the database so an administrator can change them in the admin console
and have the change take effect immediately — no restart. Values fall back to
the environment defaults in :mod:`app.config` when a key is missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting

# The classification knobs, mapped to their env-default attribute on Settings.
CLASSIFICATION_KEYS: dict[str, str] = {
    "classify_alpha": "classify_alpha",
    "confidence_high": "confidence_high",
    "margin_min": "margin_min",
    "other_threshold": "other_threshold",
    "review_threshold": "review_threshold",
    "semantic_temperature": "semantic_temperature",
    "dedupe_threshold": "dedupe_threshold",
}


@dataclass(frozen=True)
class ClassificationConfig:
    alpha: float
    confidence_high: float
    margin_min: float
    other_threshold: float
    review_threshold: float
    semantic_temperature: float
    dedupe_threshold: float


def get_value(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    if row is None:
        return default
    # Values are stored wrapped as {"value": <x>}.
    if isinstance(row.value, dict) and "value" in row.value:
        return row.value["value"]
    return row.value


def set_value(db: Session, key: str, value) -> None:
    row = db.get(AppSetting, key)
    wrapped = {"value": value}
    if row is None:
        db.add(AppSetting(key=key, value=wrapped, updated_at=datetime.now(timezone.utc)))
    else:
        row.value = wrapped
        row.updated_at = datetime.now(timezone.utc)
    db.flush()


def get_float(db: Session, key: str, default: float) -> float:
    value = get_value(db, key, None)
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def get_classification_config(db: Session) -> ClassificationConfig:
    s = get_settings()
    return ClassificationConfig(
        alpha=get_float(db, "classify_alpha", s.classify_alpha),
        confidence_high=get_float(db, "confidence_high", s.confidence_high),
        margin_min=get_float(db, "margin_min", s.margin_min),
        other_threshold=get_float(db, "other_threshold", s.other_threshold),
        review_threshold=get_float(db, "review_threshold", s.review_threshold),
        semantic_temperature=get_float(db, "semantic_temperature", s.semantic_temperature),
        dedupe_threshold=get_float(db, "dedupe_threshold", s.dedupe_threshold),
    )


def seed_defaults(db: Session) -> None:
    """Populate any missing classification settings from env defaults."""
    s = get_settings()
    for key, attr in CLASSIFICATION_KEYS.items():
        if db.get(AppSetting, key) is None:
            set_value(db, key, getattr(s, attr))


def all_settings(db: Session) -> list[AppSetting]:
    return list(db.scalars(select(AppSetting).order_by(AppSetting.key)))
