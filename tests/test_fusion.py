"""Tests for Stage 3 fusion + gating maths."""
from __future__ import annotations

from app.classification.fusion import fuse_scores, gate
from app.runtime_config import ClassificationConfig

CODES = ["ENERGY", "AGRICULTURE", "OTHER"]
CFG = ClassificationConfig(
    alpha=0.45, confidence_high=0.62, margin_min=0.15, other_threshold=0.30,
    review_threshold=0.55, semantic_temperature=0.07, dedupe_threshold=0.92,
)


def test_fusion_linear_combination():
    lex = {"ENERGY": 1.0, "AGRICULTURE": 0.0, "OTHER": 0.0}
    sem = {"ENERGY": 0.5, "AGRICULTURE": 0.5, "OTHER": 0.0}
    fused = fuse_scores(lex, sem, 0.45, CODES)
    assert abs(fused["ENERGY"] - (0.45 * 1.0 + 0.55 * 0.5)) < 1e-9
    assert abs(fused["AGRICULTURE"] - (0.55 * 0.5)) < 1e-9


def test_gate_accepts_confident_and_separated():
    fused = {"ENERGY": 0.80, "AGRICULTURE": 0.15, "OTHER": 0.05}
    sem = {"ENERGY": 0.8, "AGRICULTURE": 0.2, "OTHER": 0.0}
    g = gate(fused, sem, lexical_total_hits=3, config=CFG)
    assert g.needs_arbiter is False
    assert g.decided_by_stage == 2
    assert g.top1_code == "ENERGY"


def test_gate_invokes_arbiter_on_narrow_margin():
    fused = {"ENERGY": 0.40, "AGRICULTURE": 0.38, "OTHER": 0.02}
    sem = {"ENERGY": 0.5, "AGRICULTURE": 0.5, "OTHER": 0.0}
    g = gate(fused, sem, lexical_total_hits=2, config=CFG)
    assert g.needs_arbiter is True
    assert g.decided_by_stage == 4
    assert g.reason == "narrow_margin"


def test_gate_invokes_arbiter_on_low_confidence():
    fused = {"ENERGY": 0.50, "AGRICULTURE": 0.20, "OTHER": 0.10}
    sem = {"ENERGY": 0.6, "AGRICULTURE": 0.3, "OTHER": 0.0}
    g = gate(fused, sem, lexical_total_hits=1, config=CFG)
    # margin 0.30 >= 0.15 but top score 0.50 < 0.62 -> arbiter (low confidence)
    assert g.needs_arbiter is True
    assert g.reason == "low_confidence"


def test_gate_other_bucket_when_no_hits_and_low_semantic():
    fused = {"ENERGY": 0.10, "AGRICULTURE": 0.08, "OTHER": 0.0}
    sem = {"ENERGY": 0.20, "AGRICULTURE": 0.15, "OTHER": 0.0}  # max < 0.30
    g = gate(fused, sem, lexical_total_hits=0, config=CFG)
    assert g.assign_other is True
    assert g.top1_code == "OTHER"
    assert g.decided_by_stage == 3
    assert g.reason == "other_bucket"
