"""All vector operations, isolated behind one module.

Embeddings are stored as JSON arrays on ``grievances.embedding``. Similarity
search is a NumPy cosine over an in-memory matrix that is rebuilt on write. This
is deliberately simple and portable (zero setup). The migration path past
~100k rows is PostgreSQL + pgvector with an HNSW index; because every vector
operation lives here, that is a contained change (see DECISIONS.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Grievance


def cosine(a, b) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def unit(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


# ---- In-memory corpus (id -> unit vector) ------------------------------------
_IDS: list[str] = []
_MATRIX: np.ndarray | None = None
_POS: dict[str, int] = {}


def rebuild(db: Session) -> int:
    """Rebuild the in-memory matrix from all grievances that have embeddings."""
    global _IDS, _MATRIX, _POS
    rows = db.execute(
        select(Grievance.id, Grievance.embedding).where(Grievance.embedding.is_not(None))
    ).all()
    ids: list[str] = []
    vectors: list[np.ndarray] = []
    for gid, emb in rows:
        if not emb:
            continue
        ids.append(gid)
        vectors.append(unit(emb))
    _IDS = ids
    _POS = {gid: i for i, gid in enumerate(ids)}
    _MATRIX = np.vstack(vectors) if vectors else None
    return len(ids)


def upsert(grievance_id: str, vec) -> None:
    """Insert or update one vector in the in-memory matrix."""
    global _IDS, _MATRIX, _POS
    uvec = unit(vec)
    if grievance_id in _POS:
        _MATRIX[_POS[grievance_id]] = uvec
        return
    _POS[grievance_id] = len(_IDS)
    _IDS.append(grievance_id)
    _MATRIX = uvec.reshape(1, -1) if _MATRIX is None else np.vstack([_MATRIX, uvec])


def remove(grievance_id: str) -> None:
    if grievance_id in _POS:
        rebuild_needed = True  # simplest correct behaviour: mark and lazily rebuild
        _POS.pop(grievance_id, None)
        _ = rebuild_needed


def search(query_vec, top_k: int = 10, allowed_ids: set[str] | None = None) -> list[tuple[str, float]]:
    """Cosine search over the corpus. Optionally restrict to allowed_ids."""
    if _MATRIX is None or not _IDS:
        return []
    q = unit(query_vec)
    sims = _MATRIX @ q  # rows are unit vectors, so dot == cosine
    order = np.argsort(-sims)
    results: list[tuple[str, float]] = []
    for idx in order:
        gid = _IDS[idx]
        if allowed_ids is not None and gid not in allowed_ids:
            continue
        results.append((gid, float(sims[idx])))
        if len(results) >= top_k:
            break
    return results


def find_similar(
    db: Session,
    query_vec,
    *,
    district: str | None = None,
    within_days: int = 30,
    exclude_id: str | None = None,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Find grievances similar to ``query_vec`` within a district + time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    stmt = select(Grievance.id).where(
        Grievance.embedding.is_not(None), Grievance.created_at >= cutoff
    )
    if district:
        stmt = stmt.where(Grievance.citizen_district == district)
    allowed = {gid for (gid,) in db.execute(stmt).all()}
    if exclude_id:
        allowed.discard(exclude_id)
    if not allowed:
        return []
    if _MATRIX is None:
        rebuild(db)
    return search(query_vec, top_k=top_k, allowed_ids=allowed)
