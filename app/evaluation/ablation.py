"""The ablation study — the most important evaluation artifact.

Runs the same held-out test split through five configurations and produces one
comparison table. It answers the question a manager actually asks — "why not
just use the LLM for everything?" — with data: Config E (arbiter-only) may match
or beat Config D on accuracy but at several times the latency and LLM cost,
because it calls the model on 100% of traffic, while D reaches near-E quality by
sending only the ambiguous minority to the model.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from app.config import reload_settings
from app.classification.semantic import compute_centroids
from app.db import session_scope
from app.evaluation.runner import CONFIG_FLAGS, _apply_provider, _labels, _score_config, _test_samples
from app.llm.factory import get_llm_client
from app.models import EvalRun

CONFIG_DESCRIPTIONS = {
    "A_lexical_only": "Lexical only",
    "B_semantic_only": "Semantic only",
    "C_fusion_no_arbiter": "Lexical + semantic fusion, no arbiter",
    "D_full_cascade": "Full cascade (shipped system)",
    "E_arbiter_only": "Arbiter only (every grievance to the LLM)",
}


def _format_table(rows: list[dict]) -> str:
    header = f"{'Config':<22}{'Description':<40}{'macro-F1':>9}{'accuracy':>10}{'mean ms':>10}{'LLM/1k':>9}"
    line = "-" * len(header)
    out = [header, line]
    for r in rows:
        out.append(
            f"{r['config']:<22}{r['description']:<40}{r['macro_f1']:>9.3f}"
            f"{r['accuracy']:>10.3f}{r['mean_latency_ms']:>10.1f}{r['llm_calls_per_1000']:>9.0f}"
        )
    return "\n".join(out)


async def run_ablation(provider: str | None = None, *, persist: bool = True) -> dict:
    _apply_provider(provider)
    with session_scope() as db:
        client = get_llm_client()
        if provider:
            # Non-default provider -> different embedding space -> refit centroids.
            await compute_centroids(db, client)
        labels = _labels(db)
        samples = _test_samples(db)

        rows: list[dict] = []
        detail: dict = {}
        for config_name, flags in CONFIG_FLAGS.items():
            started = time.perf_counter()
            records, metrics = await _score_config(db, samples, labels, flags)
            duration = (time.perf_counter() - started) * 1000
            mean_latency = (
                sum(r.latency.get("total", 0.0) for r in records) / len(records) if records else 0.0
            )
            llm_per_1000 = round(metrics["arbiter_call_rate"] * 1000)
            rows.append({
                "config": config_name,
                "description": CONFIG_DESCRIPTIONS[config_name],
                "macro_f1": metrics["macro_f1"],
                "accuracy": metrics["accuracy"],
                "mean_latency_ms": round(mean_latency, 2),
                "llm_calls_per_1000": llm_per_1000,
            })
            detail[config_name] = {"metrics": metrics, "records": records}
            if persist:
                db.add(EvalRun(
                    run_name=f"ablation-{config_name}-{client.name}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
                    config={"provider": client.name, "config": config_name},
                    accuracy=metrics["accuracy"], macro_f1=metrics["macro_f1"],
                    weighted_f1=metrics["weighted_f1"], per_class=metrics["per_class"],
                    confusion_matrix=metrics["confusion_matrix"], sample_count=metrics["sample_count"],
                    duration_ms=duration,
                ))

    return {
        "provider": client.name,
        "rows": rows,
        "table_text": _format_table(rows),
        "detail": detail,
        "labels": labels,
    }
