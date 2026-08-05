"""Dispatcher — assignment, officer email, escalation, resolution, info requests.

This module is the only place that turns a classified grievance into an
assignment + officer email, and it is reused by the SLA sweeper (breach
escalation) and the officer magic-link actions (forward / resolve / info).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.email.base import EmailProvider, OutboundEmail, get_email_provider
from app.email.render import render_citizen_notice, render_officer_dispatch
from app.email.threading import new_message_id
from app.models import Grievance, Officer
from app.routing.directory import select_officer
from app.security.tokens import create_action_token, default_expiry
from app.sla.engine import compute_sla_due, next_level, target_level_for_urgency
from app.state import ActorType, Status, record_event, transition

logger = logging.getLogger("setu.dispatch")
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class DispatchResult:
    officer: Officer | None
    sent_path: str | None
    message_id: str | None
    skipped: str | None = None


def _fmt_deadline(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def _track_url(ref_no: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/track/{ref_no}"


async def _send_officer_email(
    db: Session,
    grievance: Grievance,
    officer: Officer,
    *,
    kind: str,
    provider: EmailProvider,
) -> tuple[str | None, str]:
    expiry = default_expiry(grievance.sla_due_at)
    resolve = create_action_token(db, grievance_id=grievance.id, officer_id=officer.id, action="resolve", expires_at=expiry)
    escalate = create_action_token(db, grievance_id=grievance.id, officer_id=officer.id, action="escalate", expires_at=expiry)
    info = create_action_token(db, grievance_id=grievance.id, officer_id=officer.id, action="info", expires_at=expiry)

    urgent = grievance.urgency == "CRITICAL"
    context = {
        "grievance": grievance,
        "department": grievance.department,
        "officer": officer,
        "confidence": grievance.confidence or 0.0,
        "urgency": grievance.urgency,
        "level": grievance.current_level,
        "deadline": _fmt_deadline(grievance.sla_due_at),
        "resolve_url": resolve.url,
        "escalate_url": escalate.url,
        "info_url": info.url,
        "track_url": _track_url(grievance.ref_no),
        "urgent": urgent,
        "sla_hours": 6,
    }
    html_body, text_body = render_officer_dispatch(context)

    if kind == "dispatch" and grievance.root_message_id:
        message_id = grievance.root_message_id
        in_reply_to = references = None
    else:
        message_id = new_message_id()
        in_reply_to = references = grievance.root_message_id

    subject = f"[{grievance.ref_no}] {grievance.subject}"
    if urgent:
        subject = f"[URGENT] {subject}"

    result = await provider.send(OutboundEmail(
        to=[officer.email], subject=subject, html_body=html_body, text_body=text_body,
        message_id=message_id, in_reply_to=in_reply_to, references=references,
        grievance_id=grievance.id, kind=kind,
    ))
    record_event(
        db, grievance, "email_sent", actor_type=ActorType.SYSTEM,
        note=f"{kind} email to {officer.email}",
        payload={"to": officer.email, "subject": subject, "message_id": result.message_id,
                 "path": result.path, "provider": result.provider, "ok": result.ok},
    )
    return result.path, result.message_id


async def dispatch_grievance(db: Session, grievance: Grievance, *, provider: EmailProvider | None = None) -> DispatchResult:
    provider = provider or get_email_provider()
    if grievance.status != Status.CLASSIFIED.value:
        return DispatchResult(officer=None, sent_path=None, message_id=None, skipped=f"status={grievance.status}")

    level = target_level_for_urgency(grievance.urgency)
    officer = select_officer(db, grievance.department_id, level, grievance.citizen_district)
    if officer is None:
        logger.warning("No officer for department=%s level=%s", grievance.department_id, level)
        return DispatchResult(officer=None, sent_path=None, message_id=None, skipped="no_officer")

    grievance.sla_due_at = compute_sla_due(
        db, level=level, urgency=grievance.urgency, department_id=grievance.department_id
    )
    if grievance.root_message_id is None:
        grievance.root_message_id = new_message_id()
    grievance.assigned_officer_id = officer.id

    target = Status.ESCALATED_L2 if level == "L2" else Status.ASSIGNED_L1
    transition(
        db, grievance, target, event_type="assigned",
        actor_type=ActorType.SYSTEM, actor_label=f"{officer.name} ({level})",
        note=f"Assigned to {officer.designation_en} at {level}",
        payload={"officer_id": officer.id, "level": level, "sla_due_at": grievance.sla_due_at.isoformat()},
    )
    path, message_id = await _send_officer_email(db, grievance, officer, kind="dispatch", provider=provider)
    return DispatchResult(officer=officer, sent_path=path, message_id=message_id)


async def escalate_grievance(
    db: Session,
    grievance: Grievance,
    *,
    to_level: str | None = None,
    reason: str,
    actor_type: ActorType | str = ActorType.SYSTEM,
    actor_label: str | None = None,
    provider: EmailProvider | None = None,
) -> DispatchResult:
    provider = provider or get_email_provider()
    current = grievance.current_level or "L1"
    to_level = to_level or next_level(current)

    if to_level is None:
        # L3 breach: alert the admin dashboard + digest, no further escalation.
        record_event(
            db, grievance, "sla_l3_alert", actor_type=actor_type, actor_label=actor_label,
            note=reason or "L3 SLA breached — escalated to admin dashboard",
        )
        return DispatchResult(officer=grievance.assigned_officer, sent_path=None, message_id=None, skipped="l3_alert")

    officer = select_officer(db, grievance.department_id, to_level, grievance.citizen_district)
    grievance.sla_due_at = compute_sla_due(
        db, level=to_level, urgency=grievance.urgency, department_id=grievance.department_id
    )
    if officer is not None:
        grievance.assigned_officer_id = officer.id

    target = Status.ESCALATED_L2 if to_level == "L2" else Status.ESCALATED_L3
    transition(
        db, grievance, target, event_type="escalated",
        actor_type=actor_type, actor_label=actor_label,
        note=f"Escalated to {to_level}: {reason}",
        payload={"to_level": to_level, "reason": reason,
                 "officer_id": officer.id if officer else None,
                 "sla_due_at": grievance.sla_due_at.isoformat()},
    )
    path = message_id = None
    if officer is not None:
        path, message_id = await _send_officer_email(db, grievance, officer, kind="escalation", provider=provider)
    return DispatchResult(officer=officer, sent_path=path, message_id=message_id)


async def resolve_grievance(
    db: Session,
    grievance: Grievance,
    *,
    note: str,
    actor_type: ActorType | str = ActorType.OFFICER,
    actor_label: str | None = None,
    provider: EmailProvider | None = None,
) -> None:
    grievance.resolution_note = note
    transition(
        db, grievance, Status.RESOLVED, event_type="resolved",
        actor_type=actor_type, actor_label=actor_label, note=note,
    )
    if grievance.citizen_email:
        await _notify_citizen(
            db, grievance,
            message_en="Your grievance has been marked as resolved. If it is not resolved to your satisfaction you may reopen it within 7 days.",
            message_gu="તમારી ફરિયાદ નિરાકરણ થઈ ગઈ છે. જો સંતોષકારક ન હોય તો ૭ દિવસમાં ફરી ખોલી શકો છો.",
            kind="citizen", provider=provider,
        )


async def request_info(
    db: Session,
    grievance: Grievance,
    *,
    actor_type: ActorType | str = ActorType.OFFICER,
    actor_label: str | None = None,
    provider: EmailProvider | None = None,
) -> None:
    # Pause the SLA clock (the sweeper ignores grievances with no due date).
    paused_from = grievance.sla_due_at
    grievance.sla_due_at = None
    record_event(
        db, grievance, "info_requested", actor_type=actor_type, actor_label=actor_label,
        note="Clarification requested from citizen; SLA clock paused.",
        payload={"paused_from": paused_from.isoformat() if paused_from else None},
    )
    if grievance.citizen_email:
        await _notify_citizen(
            db, grievance,
            message_en="The assigned officer needs more information to proceed with your grievance. Please reply with the requested details.",
            message_gu="તમારી ફરિયાદ આગળ વધારવા અધિકારીને વધુ માહિતી જોઈએ છે. કૃપા કરી વિગતો સાથે જવાબ આપો.",
            kind="info", provider=provider,
        )


async def notify_citizen_duplicate(db: Session, grievance: Grievance, *, provider: EmailProvider | None = None) -> None:
    if grievance.citizen_email:
        await _notify_citizen(
            db, grievance,
            message_en="Your issue is already being tracked under an existing grievance in your area. No separate action is needed.",
            message_gu="તમારો પ્રશ્ન તમારા વિસ્તારની હાલની ફરિયાદ હેઠળ પહેલેથી ટ્રેક થઈ રહ્યો છે. અલગ કાર્યવાહીની જરૂર નથી.",
            kind="citizen", provider=provider,
        )


async def _notify_citizen(db, grievance, *, message_en, message_gu, kind, provider) -> None:
    provider = provider or get_email_provider()
    html_body, text_body = render_citizen_notice({
        "grievance": grievance, "message_en": message_en, "message_gu": message_gu,
        "track_url": _track_url(grievance.ref_no),
    })
    result = await provider.send(OutboundEmail(
        to=[grievance.citizen_email], subject=f"[{grievance.ref_no}] SETU grievance update",
        html_body=html_body, text_body=text_body,
        message_id=new_message_id(), in_reply_to=grievance.root_message_id,
        references=grievance.root_message_id, grievance_id=grievance.id, kind=kind,
    ))
    record_event(
        db, grievance, "email_sent", actor_type=ActorType.SYSTEM,
        note=f"citizen {kind} email",
        payload={"to": grievance.citizen_email, "message_id": result.message_id,
                 "path": result.path, "provider": result.provider, "ok": result.ok},
    )


async def reassign_grievance(
    db: Session, grievance: Grievance, *, reason: str = "corrected", provider: EmailProvider | None = None
) -> Officer | None:
    """Re-route an already-assigned grievance to the officer of its (new) department.

    Used by active learning after a human corrects the department. Keeps the
    current level; recomputes the SLA; emails the new officer as a thread reply.
    """
    provider = provider or get_email_provider()
    level = grievance.current_level or "L1"
    officer = select_officer(db, grievance.department_id, level, grievance.citizen_district)
    if officer is None:
        return None
    grievance.assigned_officer_id = officer.id
    grievance.sla_due_at = compute_sla_due(
        db, level=level, urgency=grievance.urgency, department_id=grievance.department_id
    )
    record_event(
        db, grievance, "reassigned", actor_type=ActorType.ADMIN,
        note=reason, payload={"officer_id": officer.id, "level": level},
    )
    await _send_officer_email(db, grievance, officer, kind="escalation", provider=provider)
    return officer
