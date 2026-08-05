"""Active learning — absorb a human correction from the review queue.

On correction we: reassign + re-dispatch, write an audit event, add the sample
to the dev split, recompute the affected department centroids immediately, and —
if an unmatched content token repeats across the department's dev samples —
learn it as a new keyword (rebuilding the automaton).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.classification.lexical import invalidate_index
from app.classification.normalize import to_folded
from app.classification.semantic import recompute_department_centroid
from app.llm.base import LLMClient
from app.models import Department, GoldenSample, Grievance, Keyword, ReviewQueue
from app.routing.dispatcher import dispatch_grievance, reassign_grievance
from app.state import ActorType, Status, record_event, transition

logger = logging.getLogger("setu.active_learning")

_STOPWORDS = {"અને", "છે", "નથી", "માટે", "પણ", "કરી", "થાય", "થઈ", "માં", "ને", "નો", "ની", "થી", "પર", "કે"}


def _maybe_learn_keywords(db: Session, grievance: Grievance, dept: Department) -> list[str]:
    existing = {
        to_folded(term)
        for (term,) in db.execute(select(Keyword.term).where(Keyword.is_active.is_(True)))
    }
    dev_texts = [
        to_folded(gs.text)
        for gs in db.scalars(
            select(GoldenSample).where(
                GoldenSample.expected_department_code == dept.code, GoldenSample.split == "dev"
            )
        )
    ]
    tokens = [t for t in to_folded(f"{grievance.subject} {grievance.body_raw}").split()
              if len(t) >= 4 and t not in _STOPWORDS and any("઀" <= ch <= "૿" for ch in t)]
    learned: list[str] = []
    for tok in tokens:
        if tok in existing or tok in learned:
            continue
        repeats = sum(1 for text in dev_texts if tok in text)
        if repeats >= 2:  # the token recurs for this department -> learn it
            db.add(Keyword(
                department_id=dept.id, term=tok, term_normalized=tok, token_count=1,
                weight=1.0, source="learned", is_active=True,
            ))
            learned.append(tok)
        if len(learned) >= 2:
            break
    if learned:
        db.flush()
        invalidate_index()
    return learned


async def apply_correction(
    db: Session, review: ReviewQueue, corrected_code: str, *, client: LLMClient, provider=None
) -> dict:
    grievance = db.get(Grievance, review.grievance_id)
    new_dept = db.scalar(select(Department).where(Department.code == corrected_code))
    if new_dept is None:
        raise ValueError(f"unknown department {corrected_code}")
    old_dept = grievance.department

    record_event(
        db, grievance, "corrected", actor_type=ActorType.ADMIN, actor_label="admin",
        note=f"{old_dept.code if old_dept else '—'} -> {new_dept.code}",
        payload={"from": old_dept.code if old_dept else None, "to": new_dept.code},
    )
    grievance.department_id = new_dept.id
    grievance.confidence = 1.0  # human-confirmed

    # Reassign + re-dispatch.
    if grievance.status == Status.NEEDS_REVIEW.value:
        transition(db, grievance, Status.CLASSIFIED, event_type="reclassified", actor_type=ActorType.ADMIN)
        await dispatch_grievance(db, grievance, provider=provider)
    elif grievance.status == Status.CLASSIFIED.value:
        await dispatch_grievance(db, grievance, provider=provider)
    elif grievance.status not in {s.value for s in (Status.RESOLVED, Status.CLOSED, Status.DUPLICATE, Status.REJECTED)}:
        await reassign_grievance(db, grievance, reason="department corrected", provider=provider)

    # Resolve the review item.
    review.corrected_department_id = new_dept.id
    review.resolved_by = "admin"
    review.resolved_at = datetime.now(timezone.utc)

    # Add the sample to the dev split so it informs future centroids.
    db.add(GoldenSample(
        text=f"{grievance.subject} {grievance.body_raw}".strip(),
        expected_department_code=new_dept.code, expected_secondary=[],
        language=grievance.detected_language, tags=["learned", "correction"], split="dev",
        notes=f"absorbed from {grievance.ref_no}",
    ))
    db.flush()

    # Recompute affected centroids immediately.
    await recompute_department_centroid(db, client, new_dept)
    if old_dept is not None and old_dept.id != new_dept.id:
        await recompute_department_centroid(db, client, old_dept)

    learned = _maybe_learn_keywords(db, grievance, new_dept)
    return {"corrected_to": new_dept.code, "learned_keywords": learned}


def counters(db: Session) -> dict:
    corrections = db.scalar(
        select(func.count()).select_from(ReviewQueue).where(ReviewQueue.resolved_at.is_not(None))
    )
    keywords_learned = db.scalar(
        select(func.count()).select_from(Keyword).where(Keyword.source == "learned")
    )
    return {"corrections": corrections or 0, "keywords_learned": keywords_learned or 0}
