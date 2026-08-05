"""Phase 12 — real-embedding ablation (build sandbox only).

Runs the ablation twice on the SAME held-out test split: once with the offline
mock provider, once with LLM_PROVIDER=local (real multilingual sentence
embeddings), and regenerates the evaluation report with both tables side by
side. Only the resulting NUMBERS are committed — never the model weights.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def _main() -> int:
    from app.evaluation.ablation import run_ablation
    from app.evaluation.report import write_reports
    from app.llm.factory import get_llm_client

    # 1) Mock provider — pass provider="mock" so centroids are refit at 1024 dims
    #    regardless of prior DB state (this script may run repeatedly).
    mock_ablation = await run_ablation(provider="mock", persist=False)

    # 2) Local provider (real multilingual embeddings; refits centroids).
    local_ablation = await run_ablation(provider="local", persist=False)
    client = get_llm_client()
    # Confirm real embeddings actually loaded (not silent mock fallback).
    health = await client.health()
    dim = getattr(client, "embedding_dim", None)
    if health.degraded or dim is None:
        print("Local embeddings unavailable — aborting Phase 12 (mock fallback detected).")
        return 2

    model = os.environ.get("LOCAL_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    local_ablation.update({
        "model": model,
        "dim": dim,
        "date": date.today().isoformat(),
        "command": "LLM_PROVIDER=local python -m app.cli evaluate --ablation",
    })

    write_reports(mock_ablation, real_ablation=local_ablation)
    md = mock_ablation["detail"]["D_full_cascade"]["metrics"]["macro_f1"]
    ld = local_ablation["detail"]["D_full_cascade"]["metrics"]["macro_f1"]
    print(f"MOCK  Config-D macro-F1 = {md:.3f}")
    print(f"LOCAL Config-D macro-F1 = {ld:.3f}   (model={model}, dim={dim})")
    print("Mock ablation table:\n" + mock_ablation["table_text"])
    print("\nReal-embedding ablation table:\n" + local_ablation["table_text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
