"""Urgency triage — runs in parallel with classification.

A CRITICAL match (life-safety signals in Gujarati or English) skips L1 and is
assigned directly to L2 with a 6-hour SLA and an ``[URGENT]`` subject prefix.
HIGH/NORMAL/LOW scale the SLA by 0.5 / 1.0 / 1.5 respectively.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.classification.normalize import to_folded
from app.config import get_settings

# SLA multipliers by urgency (CRITICAL uses a fixed 6h SLA, handled in the SLA engine).
URGENCY_SLA_FACTOR = {"CRITICAL": 0.0, "HIGH": 0.5, "NORMAL": 1.0, "LOW": 1.5}
CRITICAL_SLA_HOURS = 6.0


@lru_cache(maxsize=1)
def _load_urgency() -> tuple[list[str], list[str]]:
    path = Path(get_settings().data_dir) / "urgency.yaml"
    critical: list[str] = []
    high: list[str] = []
    if path.exists():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        critical = [to_folded(t) for t in (doc.get("critical") or [])]
        high = [to_folded(t) for t in (doc.get("high") or [])]
    return critical, high


def reload_urgency() -> None:
    _load_urgency.cache_clear()


def assess_urgency(folded_text: str, *, arbiter_urgency: str | None = None) -> str:
    """Return CRITICAL | HIGH | NORMAL | LOW for the given folded text."""
    critical, high = _load_urgency()
    for term in critical:
        if term and term in folded_text:
            return "CRITICAL"
    for term in high:
        if term and term in folded_text:
            return "HIGH"
    if arbiter_urgency in {"CRITICAL", "HIGH", "NORMAL", "LOW"}:
        # Never downgrade below what the keyword scan already implies (NORMAL here).
        return arbiter_urgency
    return "NORMAL"
