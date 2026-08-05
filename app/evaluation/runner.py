"""Evaluation runner — score the classifier on the held-out test split.

Honouring the dev/test split is the clearest signal of ML competence: centroids
are fit on the dev split only, and every number reported here is computed on the
60% test split the model never saw during fitting.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.pipeline import classify_text
from app.classification.semantic import compute_centroids
from app.config import reload_settings
from app.db import session_scope
from app.evaluation.metrics import SampleRecord, compute_metrics
from app.llm.factory import get_llm_client, reset_llm_client
from app.models import Department, EvalRun, GoldenSample

CONFIG_FLAGS = {
    "A_lexical_only": {"force_lexical_only": True, "allow_arbiter": False},
    "B_semantic_only": {"force_semantic_only": True, "allow_arbiter": False},
    "C_fusion_no_arbiter": {"allow_arbiter": False},
    "D_full_cascade": {},
    "E_arbiter_only": {"force_arbiter_always": True, "allow_arbiter": True},
}


def _apply_provider(provider: str | None):
    if provider:
        os.environ["LLM_PROVIDER"] = provider
        reload_settings()
        reset_llm_client()


def _labels(db: Session) -> list[str]:
    return list(db.scalars(select(Department.code).order_by(Department.code)))


def _test_samples(db: Session) -> list[GoldenSample]:
    return list(db.scalars(select(GoldenSample).where(GoldenSample.split == "test")))


async def _score_config(db: Session, samples, labels, flags: dict) -> tuple[list[SampleRecord], dict]:
    client = get_llm_client()
    records: list[SampleRecord] = []
    for gs in samples:
        result = await classify_text(db, gs.text, client=client, **flags)
        ordered = sorted(result.fused_scores.items(), key=lambda kv: kv[1], reverse=True)
        top2 = [c for c, _ in ordered[:2]]
        if result.department_code not in top2:
            top2 = [result.department_code] + top2[:1]
        records.append(
            SampleRecord(
                text=gs.text, true=gs.expected_department_code, pred=result.department_code,
                top2=top2, confidence=result.confidence, stage=result.decided_by_stage,
                arbiter=result.arbiter_invoked, latency=result.latency_ms,
                trace=result.build_trace_payload(), tags=gs.tags or [],
            )
        )
    return records, compute_metrics(records, labels)


async def run_evaluation(provider: str | None = None, *, persist: bool = True) -> dict:
    _apply_provider(provider)
    started = time.perf_counter()
    with session_scope() as db:
        client = get_llm_client()
        if provider:
            # A non-default provider has a different embedding space; refit centroids.
            await compute_centroids(db, client)
        labels = _labels(db)
        samples = _test_samples(db)
        records, metrics = await _score_config(db, samples, labels, CONFIG_FLAGS["D_full_cascade"])
        duration_ms = (time.perf_counter() - started) * 1000
        metrics["duration_ms"] = round(duration_ms, 1)
        metrics["provider"] = client.name
        if persist:
            db.add(EvalRun(
                run_name=f"eval-{client.name}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
                config={"provider": client.name, "config": "D_full_cascade"},
                accuracy=metrics["accuracy"], macro_f1=metrics["macro_f1"],
                weighted_f1=metrics["weighted_f1"], per_class=metrics["per_class"],
                confusion_matrix=metrics["confusion_matrix"], sample_count=metrics["sample_count"],
                duration_ms=duration_ms,
            ))
        metrics["records"] = records
    return metrics
