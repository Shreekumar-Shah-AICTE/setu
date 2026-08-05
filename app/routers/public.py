"""Citizen-facing routes: submission, confirmation, tracking, reopen."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.pipeline import intake_grievance
from app.db import get_db
from app.email.base import get_email_provider
from app.models import Grievance, GrievanceEvent
from app.reference import GUJARAT_DISTRICTS
from app.routing.dispatcher import dispatch_grievance, notify_citizen_duplicate
from app.schemas import validate_submission
from app.state import ActorType, Status, transition
from app.templating import templates

router = APIRouter(tags=["public"])

REOPEN_WINDOW_DAYS = 7


def _event_time(grievance: Grievance, event_type: str) -> datetime | None:
    for ev in grievance.events:
        if ev.event_type == event_type:
            return ev.created_at
    return None


def build_timeline(grievance: Grievance) -> tuple[list[dict], int]:
    escalated_time = _event_time(grievance, "escalated")
    steps = [
        {"key": "submitted", "en": "Submitted", "gu": "ફરિયાદ મળી", "when": grievance.created_at},
        {"key": "classified", "en": "Classified", "gu": "વર્ગીકૃત", "when": _event_time(grievance, "classified")},
        {"key": "assigned", "en": "Assigned to officer", "gu": "અધિકારીને સોંપાઈ", "when": _event_time(grievance, "assigned")},
    ]
    if escalated_time or grievance.status in {"ESCALATED_L2", "ACKNOWLEDGED_L2", "ESCALATED_L3"}:
        steps.append({"key": "escalated", "en": "Escalated to senior", "gu": "ઉચ્ચ કક્ષાએ", "when": escalated_time})
    steps.append({"key": "resolved", "en": "Resolved", "gu": "નિરાકરણ", "when": grievance.resolved_at})

    done = 0
    active_marked = False
    for step in steps:
        if step["when"] is not None:
            step["state"] = "done"
            done += 1
        elif not active_marked:
            step["state"] = "active"
            active_marked = True
        else:
            step["state"] = "pending"
    progress = int(100 * done / len(steps)) if steps else 0
    return steps, progress


@router.get("/")
async def submit_form(request: Request):
    return templates.TemplateResponse(
        request, "public/submit.html", {"districts": GUJARAT_DISTRICTS, "errors": {}, "values": {}}
    )


@router.post("/submit")
async def submit(
    request: Request,
    db: Session = Depends(get_db),
    citizen_name: str = Form(""),
    citizen_phone: str = Form(""),
    citizen_email: str = Form(""),
    citizen_district: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
):
    values = {
        "citizen_name": citizen_name, "citizen_phone": citizen_phone, "citizen_email": citizen_email,
        "citizen_district": citizen_district, "subject": subject, "body": body,
    }
    errors = validate_submission(values)
    if errors:
        return templates.TemplateResponse(
            request, "public/submit.html",
            {"districts": GUJARAT_DISTRICTS, "errors": errors, "values": values}, status_code=400,
        )

    grievance, _result = await intake_grievance(
        db, citizen_name=citizen_name.strip(), subject=subject.strip(), body=body.strip(),
        citizen_email=(citizen_email.strip() or None), citizen_phone=citizen_phone.strip(),
        citizen_district=citizen_district.strip(),
    )
    provider = get_email_provider()
    if grievance.status == Status.DUPLICATE.value:
        await notify_citizen_duplicate(db, grievance, provider=provider)
    elif grievance.status == Status.CLASSIFIED.value:
        await dispatch_grievance(db, grievance, provider=provider)
    db.commit()
    return RedirectResponse(url=f"/confirmation/{grievance.ref_no}", status_code=303)


@router.get("/confirmation/{ref_no}")
async def confirmation(ref_no: str, request: Request, db: Session = Depends(get_db)):
    grievance = db.scalar(select(Grievance).where(Grievance.ref_no == ref_no))
    if grievance is None:
        return templates.TemplateResponse(request, "public/not_found.html", {"ref_no": ref_no}, status_code=404)
    return templates.TemplateResponse(request, "public/confirmation.html", {"grievance": grievance})


@router.get("/track")
async def track_form(request: Request):
    return templates.TemplateResponse(request, "public/track_form.html", {})


@router.get("/track/{ref_no}")
async def track(ref_no: str, request: Request, db: Session = Depends(get_db)):
    grievance = db.scalar(select(Grievance).where(Grievance.ref_no == ref_no))
    if grievance is None:
        return templates.TemplateResponse(request, "public/not_found.html", {"ref_no": ref_no}, status_code=404)
    steps, progress = build_timeline(grievance)
    reopen_ok = grievance.status in {Status.RESOLVED.value, Status.CLOSED.value} and (
        grievance.resolved_at is not None
        and _aware(grievance.resolved_at) > datetime.now(timezone.utc) - timedelta(days=REOPEN_WINDOW_DAYS)
    )
    return templates.TemplateResponse(
        request, "public/track.html",
        {"grievance": grievance, "steps": steps, "progress": progress, "reopen_ok": reopen_ok},
    )


@router.post("/track/{ref_no}/reopen")
async def reopen(ref_no: str, request: Request, db: Session = Depends(get_db)):
    grievance = db.scalar(select(Grievance).where(Grievance.ref_no == ref_no))
    if grievance is None:
        return templates.TemplateResponse(request, "public/not_found.html", {"ref_no": ref_no}, status_code=404)

    eligible = grievance.status in {Status.RESOLVED.value, Status.CLOSED.value} and (
        grievance.resolved_at is not None
        and _aware(grievance.resolved_at) > datetime.now(timezone.utc) - timedelta(days=REOPEN_WINDOW_DAYS)
    )
    if eligible:
        transition(db, grievance, Status.REOPENED, event_type="reopened",
                   actor_type=ActorType.CITIZEN, actor_label=grievance.citizen_name,
                   note="Citizen reopened the grievance")
        transition(db, grievance, Status.CLASSIFIED, event_type="reclassified", actor_type=ActorType.SYSTEM)
        await dispatch_grievance(db, grievance, provider=get_email_provider())
        db.commit()
    return RedirectResponse(url=f"/track/{ref_no}", status_code=303)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
