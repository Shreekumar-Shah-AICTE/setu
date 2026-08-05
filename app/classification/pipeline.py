"""The classification pipeline — orchestrates Stages 0–4.

``classify_text`` runs the cascade and returns a rich result (scores, chosen
department, trace payload, embedding) without persisting anything — used by the
evaluation harness and the ``POST /classify`` demo endpoint.

``intake_grievance`` creates a Grievance row, runs the cascade, performs
duplicate detection, persists the ClassificationTrace, sets the status via the
state machine and (when warranted) creates a review-queue entry. Routing and
email dispatch are performed separately by the dispatcher.
"""
from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification import arbiter as arbiter_mod
from app.classification.dedupe import check_duplicate
from app.classification.fusion import GateResult, fuse_scores, gate
from app.classification.lexical import match_text
from app.classification.normalize import NormalizedText, normalize
from app.classification.semantic import ensure_centroids, load_centroids, semantic_scores
from app.classification.urgency import assess_urgency
from app.llm.base import LLMClient
from app.llm.catalogue import EMBEDDING_MODEL
from app.llm.factory import get_llm_client
from app.models import ClassificationTrace, Department, Grievance, ReviewQueue
from app.runtime_config import get_classification_config
from app.state import ActorType, Status, record_event, transition


def generate_ref_no(now: datetime | None = None) -> str:
    """SETU-YYYYMMDD-XXXXXX where X is base32 from a CSPRNG (non-guessable)."""
    now = now or datetime.now(timezone.utc)
    token = base64.b32encode(secrets.token_bytes(5)).decode("ascii").rstrip("=")[:6]
    return f"SETU-{now:%Y%m%d}-{token}"


@dataclass
class ClassificationResult:
    normalized: NormalizedText
    department_code: str
    secondary_codes: list[str]
    confidence: float
    urgency: str
    language: str
    decided_by_stage: int
    gate: GateResult
    lexical_scores: dict[str, float]
    lexical_hits: list[dict]
    semantic_scores: dict[str, float]
    fused_scores: dict[str, float]
    embedding: list[float]
    provider: str
    degraded: bool
    arbiter_invoked: bool
    arbiter_raw: Optional[str]
    arbiter_parsed: Optional[dict]
    status_target: str            # CLASSIFIED | NEEDS_REVIEW
    review_reason: Optional[str]
    latency_ms: dict[str, float] = field(default_factory=dict)

    def build_trace_payload(self) -> dict:
        return {
            "normalized_text": self.normalized.folded,
            "lexical_scores": self.lexical_scores,
            "lexical_hits": self.lexical_hits,
            "semantic_scores": self.semantic_scores,
            "fused_scores": self.fused_scores,
            "arbiter_invoked": self.arbiter_invoked,
            "arbiter_raw": self.arbiter_raw,
            "arbiter_parsed": self.arbiter_parsed,
            "chosen_department_code": self.department_code,
            "confidence": self.confidence,
            "margin": self.gate.margin,
            "decided_by_stage": self.decided_by_stage,
            "degraded": self.degraded,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
        }


def _departments_for_arbiter(db: Session) -> list[tuple[str, str, str]]:
    rows = db.execute(
        select(Department.code, Department.name_en, Department.name_gu).where(Department.is_active.is_(True))
    ).all()
    return [(c, e, g) for c, e, g in rows]


async def classify_text(
    db: Session,
    text: str,
    subject: str = "",
    *,
    client: LLMClient | None = None,
    allow_arbiter: bool = True,
    force_semantic_only: bool = False,
    force_lexical_only: bool = False,
    force_arbiter_always: bool = False,
) -> ClassificationResult:
    client = client or get_llm_client()
    config = get_classification_config(db)
    latency: dict[str, float] = {}

    combined = f"{subject} {text}".strip() if subject else text

    t = time.perf_counter()
    nt = normalize(combined)
    latency["normalize"] = (time.perf_counter() - t) * 1000

    all_codes = list(
        db.scalars(select(Department.code).where(Department.is_active.is_(True)).order_by(Department.code))
    )

    # Stage 1 — lexical
    t = time.perf_counter()
    lex = match_text(db, nt.folded)
    latency["lexical"] = (time.perf_counter() - t) * 1000

    # Embedding (shared by semantic + dedupe + storage)
    t = time.perf_counter()
    await ensure_centroids(db, client)
    embedding = (await client.embed(model=EMBEDDING_MODEL, texts=[nt.normalized]))[0]
    latency["embed"] = (time.perf_counter() - t) * 1000

    # Stage 2 — semantic
    t = time.perf_counter()
    centroids = load_centroids(db)
    sem = semantic_scores(embedding, centroids, config.semantic_temperature, all_codes)
    latency["semantic"] = (time.perf_counter() - t) * 1000

    # Ablation overrides
    if force_lexical_only:
        sem = {code: 0.0 for code in all_codes}
    if force_semantic_only:
        lex_scores = {code: 0.0 for code in all_codes}
        lex_hits_for_fusion = 1  # avoid OTHER-bucket shortcut in semantic-only mode
    else:
        lex_scores = lex.scores
        lex_hits_for_fusion = lex.total_hits

    # Stage 3 — fusion + gate
    t = time.perf_counter()
    alpha = 0.0 if force_semantic_only else (1.0 if force_lexical_only else config.alpha)
    fused = fuse_scores(lex_scores, sem, alpha, all_codes)
    g = gate(fused, sem, lex_hits_for_fusion, config)
    latency["fusion"] = (time.perf_counter() - t) * 1000

    lexical_hits = [h.as_dict() for h in lex.hits]

    # Defaults (Stage 2/3 acceptance)
    department_code = g.top1_code
    secondary_codes: list[str] = []
    confidence = g.top1_score
    language = nt.language
    decided_by_stage = g.decided_by_stage
    degraded = False
    arbiter_invoked = False
    arbiter_raw: Optional[str] = None
    arbiter_parsed: Optional[dict] = None
    status_target = Status.CLASSIFIED.value
    review_reason: Optional[str] = None
    arbiter_urgency: Optional[str] = None

    if g.assign_other and not force_arbiter_always:
        department_code = "OTHER"
        review_reason = "other_bucket"

    # Stage 4 — arbiter
    run_arbiter = allow_arbiter and (force_arbiter_always or (g.needs_arbiter and not g.assign_other))
    if run_arbiter:
        t = time.perf_counter()
        result = await arbiter_mod.run_arbiter(
            client,
            grievance_text=combined,
            language=nt.language,
            departments=_departments_for_arbiter(db),
            lexical_hits=lexical_hits,
            candidates=g.ordered,
        )
        latency["arbiter"] = (time.perf_counter() - t) * 1000
        arbiter_invoked = True
        arbiter_raw = result.raw
        degraded = result.degraded
        decided_by_stage = 4
        if result.parsed is not None:
            parsed = result.parsed
            arbiter_parsed = parsed.model_dump()
            department_code = parsed.department
            secondary_codes = [c for c in parsed.secondary_departments if c in all_codes and c != department_code]
            confidence = parsed.confidence
            language = parsed.detected_language or nt.language
            arbiter_urgency = parsed.urgency
            if confidence < config.review_threshold:
                status_target = Status.NEEDS_REVIEW.value
                review_reason = "low_confidence"
            elif secondary_codes and confidence < 0.80:
                review_reason = "multi_department"
        else:
            # Arbiter failed twice -> fall back to fused winner, flag for review.
            department_code = g.top1_code
            confidence = g.top1_score
            status_target = Status.NEEDS_REVIEW.value
            review_reason = "low_confidence"

    # Urgency (parallel signal); CRITICAL always wins.
    urgency = assess_urgency(nt.folded, arbiter_urgency=arbiter_urgency)

    latency["total"] = sum(v for k, v in latency.items() if k != "total")

    return ClassificationResult(
        normalized=nt,
        department_code=department_code,
        secondary_codes=secondary_codes,
        confidence=confidence,
        urgency=urgency,
        language=language,
        decided_by_stage=decided_by_stage,
        gate=g,
        lexical_scores=lex.scores,
        lexical_hits=lexical_hits,
        semantic_scores=sem,
        fused_scores=fused,
        embedding=embedding,
        provider=client.name,
        degraded=degraded,
        arbiter_invoked=arbiter_invoked,
        arbiter_raw=arbiter_raw,
        arbiter_parsed=arbiter_parsed,
        status_target=status_target,
        review_reason=review_reason,
        latency_ms=latency,
    )


async def intake_grievance(
    db: Session,
    *,
    citizen_name: str,
    subject: str,
    body: str,
    citizen_email: str | None = None,
    citizen_phone: str | None = None,
    citizen_district: str | None = None,
    client: LLMClient | None = None,
    created_at: datetime | None = None,
) -> tuple[Grievance, ClassificationResult]:
    """Create and classify a grievance. Does not dispatch email (see dispatcher)."""
    client = client or get_llm_client()
    config = get_classification_config(db)

    # Unique ref number (retry on the astronomically unlikely collision).
    for _ in range(5):
        ref_no = generate_ref_no(created_at)
        if not db.scalar(select(Grievance.id).where(Grievance.ref_no == ref_no)):
            break

    grievance = Grievance(
        ref_no=ref_no,
        citizen_name=citizen_name,
        citizen_email=citizen_email,
        citizen_phone=citizen_phone,
        citizen_district=citizen_district,
        subject=subject,
        body_raw=body,
        status=Status.RECEIVED.value,
    )
    if created_at is not None:
        grievance.created_at = created_at
        grievance.updated_at = created_at
    db.add(grievance)
    db.flush()
    record_event(db, grievance, "received", actor_type=ActorType.CITIZEN, actor_label=citizen_name)

    result = await classify_text(db, body, subject, client=client)

    grievance.body_normalized = result.normalized.normalized
    grievance.detected_language = result.language
    grievance.embedding = result.embedding
    grievance.confidence = result.confidence
    grievance.decided_by_stage = result.decided_by_stage

    # Duplicate detection (skip a second officer email; link to the original).
    dup = check_duplicate(
        db, result.embedding, district=citizen_district, threshold=config.dedupe_threshold,
        exclude_id=grievance.id,
    )
    code_to_dept = {d.code: d for d in db.scalars(select(Department))}

    if dup is not None:
        grievance.duplicate_of_id = dup.grievance_id
        transition(
            db, grievance, Status.DUPLICATE, event_type="duplicate_detected",
            note=f"Similar to existing grievance (score {dup.score:.3f})",
            payload={"duplicate_of": dup.grievance_id, "score": dup.score},
        )
        _persist_trace(db, grievance, result)
        return grievance, result

    dept = code_to_dept.get(result.department_code) or code_to_dept.get("OTHER")
    grievance.department_id = dept.id if dept else None
    grievance.secondary_department_ids = [
        code_to_dept[c].id for c in result.secondary_codes if c in code_to_dept
    ]
    grievance.urgency = result.urgency

    transition(
        db, grievance, Status(result.status_target), event_type="classified",
        note=f"{result.department_code} (stage {result.decided_by_stage}, conf {result.confidence:.2f})",
        payload={
            "department": result.department_code,
            "secondary": result.secondary_codes,
            "confidence": result.confidence,
            "urgency": result.urgency,
            "decided_by_stage": result.decided_by_stage,
        },
    )

    _persist_trace(db, grievance, result)

    # Update the in-memory vector corpus for future dedupe/search.
    from app.vectors import upsert as vector_upsert

    vector_upsert(grievance.id, result.embedding)

    if result.review_reason:
        db.add(
            ReviewQueue(
                grievance_id=grievance.id,
                reason=result.review_reason,
                suggested_department_id=dept.id if dept else None,
            )
        )
        db.flush()

    return grievance, result


def _persist_trace(db: Session, grievance: Grievance, result: ClassificationResult) -> None:
    payload = result.build_trace_payload()
    trace = ClassificationTrace(grievance_id=grievance.id, **payload)
    db.add(trace)
    db.flush()
