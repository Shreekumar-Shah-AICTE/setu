"""JSON API (/api/v1)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.classification.pipeline import classify_text, intake_grievance
from app.db import get_db
from app.email.base import get_email_provider
from app.llm.factory import get_llm_client
from app.models import Department, Grievance
from app.routing.dispatcher import dispatch_grievance, notify_citizen_duplicate
from app.schemas import ClassifyRequest, GrievanceCreate
from app.state import Status

router = APIRouter(prefix="/api/v1", tags=["api"])


def _grievance_out(g: Grievance) -> dict:
    return {
        "ref_no": g.ref_no,
        "status": g.status,
        "department": g.department.code if g.department else None,
        "urgency": g.urgency,
        "confidence": g.confidence,
        "current_level": g.current_level,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "sla_due_at": g.sla_due_at.isoformat() if g.sla_due_at else None,
        "duplicate_of": g.duplicate_of_id,
    }


@router.post("/grievances")
async def create_grievance(payload: GrievanceCreate, db: Session = Depends(get_db)):
    grievance, _ = await intake_grievance(
        db, citizen_name=payload.citizen_name, subject=payload.subject, body=payload.body,
        citizen_email=payload.citizen_email, citizen_phone=payload.citizen_phone,
        citizen_district=payload.citizen_district,
    )
    provider = get_email_provider()
    if grievance.status == Status.DUPLICATE.value:
        await notify_citizen_duplicate(db, grievance, provider=provider)
    elif grievance.status == Status.CLASSIFIED.value:
        await dispatch_grievance(db, grievance, provider=provider)
    db.commit()
    return _grievance_out(grievance)


@router.get("/grievances/{ref_no}")
async def get_grievance(ref_no: str, db: Session = Depends(get_db)):
    g = db.scalar(select(Grievance).where(Grievance.ref_no == ref_no))
    if g is None:
        raise HTTPException(status_code=404, detail="grievance not found")
    return _grievance_out(g)


@router.post("/classify")
async def classify_only(payload: ClassifyRequest, db: Session = Depends(get_db)):
    """Classify without persisting — useful for demos."""
    result = await classify_text(db, payload.body, payload.subject, client=get_llm_client())
    return {
        "department": result.department_code,
        "secondary_departments": result.secondary_codes,
        "confidence": result.confidence,
        "urgency": result.urgency,
        "detected_language": result.language,
        "decided_by_stage": result.decided_by_stage,
        "degraded": result.degraded,
        "provider": result.provider,
        "lexical_scores": result.lexical_scores,
        "semantic_scores": result.semantic_scores,
        "fused_scores": result.fused_scores,
        "latency_ms": result.latency_ms,
    }


@router.get("/departments")
async def list_departments(db: Session = Depends(get_db)):
    rows = db.scalars(select(Department).where(Department.is_active.is_(True)).order_by(Department.code))
    return [{"code": d.code, "name_en": d.name_en, "name_gu": d.name_gu} for d in rows]


@router.get("/stats")
async def stats(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Grievance))
    by_status = dict(db.execute(select(Grievance.status, func.count()).group_by(Grievance.status)).all())
    by_dept = dict(
        db.execute(
            select(Department.code, func.count(Grievance.id))
            .join(Grievance, Grievance.department_id == Department.id, isouter=True)
            .group_by(Department.code)
        ).all()
    )
    return {"total": total, "by_status": by_status, "by_department": by_dept}


@router.get("/health")
async def api_health(db: Session = Depends(get_db)):
    client = get_llm_client()
    health = await client.health()
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "database": "ok",
        "provider": {"name": health.provider, "healthy": health.healthy, "degraded": health.degraded},
    }
