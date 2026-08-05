"""Stage 2 — semantic matcher (department centroids + cosine + softmax).

Each department has a centroid vector: the L2-normalised mean of the embeddings
of (a) its keywords and (b) every dev-split golden sample labelled to it.
Centroids are computed at seed time, cached on ``departments.centroid`` and
recomputed whenever a human corrects a classification. OTHER has no centroid —
it is assigned by the fusion stage when everything else scores low.

Classification is by cosine similarity between the grievance embedding and each
centroid, turned into a probability distribution by a softmax with temperature
0.07.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.base import LLMClient
from app.llm.catalogue import EMBEDDING_MODEL
from app.models import Department, GoldenSample, Keyword
from app.vectors import cosine, unit

logger = logging.getLogger("setu.semantic")


async def _embed_texts(client: LLMClient, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await client.embed(model=EMBEDDING_MODEL, texts=texts)


async def compute_centroids(db: Session, client: LLMClient) -> int:
    """Recompute centroids for every active department (except OTHER)."""
    departments = list(db.scalars(select(Department).where(Department.is_active.is_(True))))
    computed = 0
    for dept in departments:
        if dept.code == "OTHER":
            dept.centroid = None
            continue
        texts: list[str] = [
            kw.term for kw in db.scalars(
                select(Keyword).where(Keyword.department_id == dept.id, Keyword.is_active.is_(True))
            )
        ]
        texts += [
            gs.text for gs in db.scalars(
                select(GoldenSample).where(
                    GoldenSample.expected_department_code == dept.code, GoldenSample.split == "dev"
                )
            )
        ]
        if not texts:
            dept.centroid = None
            continue
        embeddings = await _embed_texts(client, texts)
        mean = [sum(col) / len(embeddings) for col in zip(*embeddings)]
        dept.centroid = unit(mean).tolist()
        dept.centroid_updated_at = datetime.now(timezone.utc)
        computed += 1
    db.flush()
    logger.info("Computed %d department centroids", computed)
    return computed


async def recompute_department_centroid(db: Session, client: LLMClient, department: Department) -> None:
    """Recompute a single department's centroid (used on human correction)."""
    if department.code == "OTHER":
        department.centroid = None
        db.flush()
        return
    texts = [
        kw.term for kw in db.scalars(
            select(Keyword).where(Keyword.department_id == department.id, Keyword.is_active.is_(True))
        )
    ]
    texts += [
        gs.text for gs in db.scalars(
            select(GoldenSample).where(
                GoldenSample.expected_department_code == department.code, GoldenSample.split == "dev"
            )
        )
    ]
    if not texts:
        department.centroid = None
        db.flush()
        return
    embeddings = await _embed_texts(client, texts)
    mean = [sum(col) / len(embeddings) for col in zip(*embeddings)]
    department.centroid = unit(mean).tolist()
    department.centroid_updated_at = datetime.now(timezone.utc)
    db.flush()


def load_centroids(db: Session) -> dict[str, list[float]]:
    rows = db.execute(
        select(Department.code, Department.centroid).where(
            Department.is_active.is_(True), Department.centroid.is_not(None)
        )
    ).all()
    return {code: centroid for code, centroid in rows if centroid}


def has_centroids(db: Session) -> bool:
    return bool(load_centroids(db))


async def ensure_centroids(db: Session, client: LLMClient) -> None:
    """Compute centroids on first use if none exist yet."""
    if not has_centroids(db):
        await compute_centroids(db, client)


def semantic_scores(
    query_vec: list[float], centroids: dict[str, list[float]], temperature: float, all_codes: list[str]
) -> dict[str, float]:
    """Softmax over cosine similarities. Codes without a centroid score 0."""
    scores = {code: 0.0 for code in all_codes}
    if not centroids or not query_vec:
        return scores
    codes = list(centroids.keys())
    sims = [cosine(query_vec, centroids[c]) for c in codes]
    temperature = max(temperature, 1e-6)
    scaled = [s / temperature for s in sims]
    m = max(scaled)
    exps = [math.exp(s - m) for s in scaled]
    total = sum(exps)
    for code, e in zip(codes, exps):
        scores[code] = e / total if total > 0 else 0.0
    return scores
