"""Evaluation metrics, implemented from scratch with NumPy (no scikit-learn).

Headline metric is **macro-F1**: departments are imbalanced, and macro-F1
refuses to let big classes hide failures on small ones — it averages the
per-class F1 with equal weight, so a department with three test samples counts
as much as one with seventeen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SampleRecord:
    text: str
    true: str
    pred: str
    top2: list[str]
    confidence: float
    stage: int
    arbiter: bool
    latency: dict[str, float]
    trace: dict | None = None
    tags: list[str] = field(default_factory=list)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), p))


def compute_metrics(records: list[SampleRecord], labels: list[str]) -> dict:
    n = len(records)
    index = {code: i for i, code in enumerate(labels)}
    k = len(labels)
    cm = np.zeros((k, k), dtype=np.int64)  # rows = true, cols = pred
    for r in records:
        if r.true in index and r.pred in index:
            cm[index[r.true], index[r.pred]] += 1

    support = cm.sum(axis=1)
    predicted = cm.sum(axis=0)
    tp = np.diag(cm)
    fp = predicted - tp
    fn = support - tp

    precision = np.divide(tp, tp + fp, out=np.zeros(k), where=(tp + fp) > 0)
    recall = np.divide(tp, tp + fn, out=np.zeros(k), where=(tp + fn) > 0)
    f1 = np.divide(2 * precision * recall, precision + recall,
                   out=np.zeros(k), where=(precision + recall) > 0)

    per_class = {
        labels[i]: {
            "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4),
            "f1": round(float(f1[i]), 4),
            "support": int(support[i]),
        }
        for i in range(k)
    }

    present = support > 0  # classes with at least one test sample
    macro_f1 = float(f1[present].mean()) if present.any() else 0.0
    total_support = support.sum()
    weighted_f1 = float((f1 * support).sum() / total_support) if total_support > 0 else 0.0
    accuracy = float(tp.sum() / n) if n else 0.0

    top2_hits = sum(1 for r in records if r.true in (r.top2 or []))
    top2_accuracy = top2_hits / n if n else 0.0

    correct_conf = [r.confidence for r in records if r.pred == r.true and r.confidence is not None]
    incorrect_conf = [r.confidence for r in records if r.pred != r.true and r.confidence is not None]
    mean_conf_correct = float(np.mean(correct_conf)) if correct_conf else 0.0
    mean_conf_incorrect = float(np.mean(incorrect_conf)) if incorrect_conf else 0.0

    stage_usage: dict[str, int] = {}
    for r in records:
        key = f"stage_{r.stage}"
        stage_usage[key] = stage_usage.get(key, 0) + 1
    arbiter_calls = sum(1 for r in records if r.arbiter)

    stage_keys = set()
    for r in records:
        stage_keys.update(r.latency.keys())
    latency_pct = {}
    for key in sorted(stage_keys):
        vals = [r.latency[key] for r in records if key in r.latency]
        latency_pct[key] = {"p50": round(_percentile(vals, 50), 3), "p95": round(_percentile(vals, 95), 3)}

    return {
        "sample_count": n,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "weighted_f1": round(weighted_f1, 4),
        "top2_accuracy": round(top2_accuracy, 4),
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "matrix": cm.tolist()},
        "mean_confidence_correct": round(mean_conf_correct, 4),
        "mean_confidence_incorrect": round(mean_conf_incorrect, 4),
        "stage_usage": stage_usage,
        "arbiter_calls": arbiter_calls,
        "arbiter_call_rate": round(arbiter_calls / n, 4) if n else 0.0,
        "latency_ms": latency_pct,
    }
