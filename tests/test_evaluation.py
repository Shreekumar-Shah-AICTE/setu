"""Tests for the evaluation metrics, verified against hand-computed values."""
from __future__ import annotations

from app.evaluation.metrics import SampleRecord, compute_metrics

LABELS = ["A", "B", "C"]


def _rec(true, pred, top2=None, conf=0.9, stage=2):
    return SampleRecord(
        text="x", true=true, pred=pred, top2=top2 or [pred, true],
        confidence=conf, stage=stage, arbiter=(stage == 4), latency={"total": 1.0},
    )


def _metrics():
    records = [
        _rec("A", "A"), _rec("A", "A"), _rec("A", "B"),
        _rec("B", "B"), _rec("B", "C"),
        _rec("C", "C"),
    ]
    return compute_metrics(records, LABELS)


def test_accuracy_hand_computed():
    m = _metrics()
    # 4 correct out of 6
    assert abs(m["accuracy"] - 4 / 6) < 1e-4


def test_per_class_precision_recall_f1():
    pc = _metrics()["per_class"]
    assert abs(pc["A"]["precision"] - 1.0) < 1e-4
    assert abs(pc["A"]["recall"] - 2 / 3) < 1e-4
    assert abs(pc["A"]["f1"] - 0.8) < 1e-4
    assert abs(pc["B"]["precision"] - 0.5) < 1e-4
    assert abs(pc["B"]["recall"] - 0.5) < 1e-4
    assert abs(pc["C"]["recall"] - 1.0) < 1e-4
    assert pc["A"]["support"] == 3


def test_macro_and_weighted_f1():
    m = _metrics()
    # f1: A=0.8, B=0.5, C=0.6667
    assert abs(m["macro_f1"] - (0.8 + 0.5 + (2 / 3)) / 3) < 1e-3
    assert abs(m["weighted_f1"] - (0.8 * 3 + 0.5 * 2 + (2 / 3) * 1) / 6) < 1e-3


def test_confusion_matrix_shape_and_counts():
    m = _metrics()
    cm = m["confusion_matrix"]
    assert cm["labels"] == LABELS
    # true A -> [A:2, B:1, C:0]
    assert cm["matrix"][0] == [2, 1, 0]
    assert cm["matrix"][1] == [0, 1, 1]
    assert cm["matrix"][2] == [0, 0, 1]


def test_top2_accuracy_and_confidence_split():
    records = [
        _rec("A", "A", top2=["A", "B"], conf=0.9),
        _rec("A", "B", top2=["B", "C"], conf=0.4),  # true A not in top2 -> miss
    ]
    m = compute_metrics(records, LABELS)
    assert abs(m["top2_accuracy"] - 0.5) < 1e-4
    assert abs(m["mean_confidence_correct"] - 0.9) < 1e-4
    assert abs(m["mean_confidence_incorrect"] - 0.4) < 1e-4


def test_stage_usage_and_latency_percentiles():
    records = [_rec("A", "A", stage=2), _rec("B", "B", stage=4), _rec("C", "C", stage=4)]
    m = compute_metrics(records, LABELS)
    assert m["stage_usage"]["stage_4"] == 2
    assert m["arbiter_calls"] == 2
    assert "total" in m["latency_ms"]


async def test_run_evaluation_smoke():
    from app.evaluation.runner import run_evaluation

    res = await run_evaluation(persist=False)
    assert res["sample_count"] > 0
    assert 0.0 <= res["macro_f1"] <= 1.0
    assert 0.0 <= res["accuracy"] <= 1.0
