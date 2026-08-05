"""Stage 3 — fusion and gating.

    fused[d] = ALPHA * lexical[d] + (1 - ALPHA) * semantic[d]

The gate decides whether the fused winner is confident enough to accept
directly (Stage 2) or must be sent to the LLM arbiter (Stage 4). The whole point
of the cascade is that only the genuinely ambiguous minority reaches the
arbiter.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.runtime_config import ClassificationConfig


@dataclass
class GateResult:
    fused: dict[str, float]
    top1_code: str
    top1_score: float
    top2_code: str | None
    top2_score: float
    margin: float
    needs_arbiter: bool
    assign_other: bool
    decided_by_stage: int
    reason: str | None = None
    ordered: list[tuple[str, float]] = field(default_factory=list)


def fuse_scores(
    lexical: dict[str, float], semantic: dict[str, float], alpha: float, all_codes: list[str]
) -> dict[str, float]:
    return {
        code: alpha * lexical.get(code, 0.0) + (1.0 - alpha) * semantic.get(code, 0.0)
        for code in all_codes
    }


def gate(
    fused: dict[str, float],
    semantic: dict[str, float],
    lexical_total_hits: int,
    config: ClassificationConfig,
) -> GateResult:
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    top1_code, top1_score = ordered[0]
    top2_code, top2_score = (ordered[1] if len(ordered) > 1 else (None, 0.0))
    margin = top1_score - top2_score

    max_semantic = max(semantic.values(), default=0.0)

    # Rule 1: no lexical evidence and weak semantics -> OTHER + review.
    if lexical_total_hits == 0 and max_semantic < config.other_threshold:
        return GateResult(
            fused=fused, top1_code="OTHER", top1_score=top1_score, top2_code=top2_code,
            top2_score=top2_score, margin=margin, needs_arbiter=False, assign_other=True,
            decided_by_stage=3, reason="other_bucket", ordered=ordered,
        )

    # Rule 2: confident and well-separated -> accept directly (skip the arbiter).
    if top1_score >= config.confidence_high and margin >= config.margin_min:
        return GateResult(
            fused=fused, top1_code=top1_code, top1_score=top1_score, top2_code=top2_code,
            top2_score=top2_score, margin=margin, needs_arbiter=False, assign_other=False,
            decided_by_stage=2, reason=None, ordered=ordered,
        )

    # Rule 3: uncertain -> arbiter.
    reason = "narrow_margin" if margin < config.margin_min else "low_confidence"
    return GateResult(
        fused=fused, top1_code=top1_code, top1_score=top1_score, top2_code=top2_code,
        top2_score=top2_score, margin=margin, needs_arbiter=True, assign_other=False,
        decided_by_stage=4, reason=reason, ordered=ordered,
    )
