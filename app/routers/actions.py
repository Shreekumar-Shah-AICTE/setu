"""Officer magic-link action endpoints.

GET renders a confirmation page and NEVER mutates state (email clients and
scanners prefetch links). POST performs the single-use action.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.email.base import get_email_provider
from app.models import Grievance, Officer
from app.routing.dispatcher import escalate_grievance, request_info, resolve_grievance
from app.security.tokens import mark_used, verify_action_token
from app.state import ActorType, InvalidTransitionError
from app.templating import templates

router = APIRouter(tags=["actions"])

ACTION_TITLES = {
    "resolve": ("Mark as Resolved", "નિરાકરણ થયું"),
    "escalate": ("Forward to Senior", "વરિષ્ઠને મોકલો"),
    "info": ("Request more information", "વધુ માહિતી માંગો"),
}


@router.get("/action/{token}")
async def action_confirm(token: str, request: Request, db: Session = Depends(get_db)):
    verified = verify_action_token(db, token)
    if not verified.valid:
        return templates.TemplateResponse(
            request, "actions/invalid.html", {"reason": verified.reason}, status_code=410 if verified.reason != "invalid" else 404
        )
    row = verified.token
    grievance = db.get(Grievance, row.grievance_id)
    officer = db.get(Officer, row.officer_id)
    title_en, title_gu = ACTION_TITLES.get(row.action, ("Action", "કાર્યવાહી"))
    return templates.TemplateResponse(
        request,
        "actions/confirm.html",
        {
            "token": token, "action": row.action, "grievance": grievance, "officer": officer,
            "action_title_en": title_en, "action_title_gu": title_gu,
        },
    )


@router.post("/action/{token}")
async def action_perform(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    note: str = Form(default=""),
    reason: str = Form(default=""),
):
    verified = verify_action_token(db, token)
    if not verified.valid:
        return templates.TemplateResponse(
            request, "actions/invalid.html", {"reason": verified.reason}, status_code=410 if verified.reason != "invalid" else 404
        )
    row = verified.token
    grievance = db.get(Grievance, row.grievance_id)
    officer = db.get(Officer, row.officer_id)
    provider = get_email_provider()
    actor_label = officer.name if officer else "officer"

    result_ctx = {"grievance": grievance}
    try:
        if row.action == "resolve":
            if not note.strip():
                return templates.TemplateResponse(
                    request, "actions/confirm.html",
                    {"token": token, "action": "resolve", "grievance": grievance, "officer": officer,
                     "action_title_en": "Mark as Resolved", "action_title_gu": "નિરાકરણ થયું"},
                    status_code=400,
                )
            await resolve_grievance(db, grievance, note=note.strip(), actor_type=ActorType.OFFICER,
                                    actor_label=actor_label, provider=provider)
            result_ctx |= {"heading_en": "Grievance resolved", "heading_gu": "ફરિયાદ નિરાકરણ થઈ",
                           "detail_en": "The grievance has been marked resolved and the citizen notified.",
                           "detail_gu": "ફરિયાદ નિરાકરણ તરીકે નોંધાઈ અને નાગરિકને જાણ કરાઈ."}
        elif row.action == "escalate":
            if not reason.strip():
                return templates.TemplateResponse(
                    request, "actions/confirm.html",
                    {"token": token, "action": "escalate", "grievance": grievance, "officer": officer,
                     "action_title_en": "Forward to Senior", "action_title_gu": "વરિષ્ઠને મોકલો"},
                    status_code=400,
                )
            await escalate_grievance(db, grievance, reason=reason.strip(), actor_type=ActorType.OFFICER,
                                     actor_label=actor_label, provider=provider)
            result_ctx |= {"heading_en": "Forwarded to senior", "heading_gu": "વરિષ્ઠને મોકલાઈ",
                           "detail_en": "The grievance has been escalated to the next level with your reason.",
                           "detail_gu": "તમારા કારણ સાથે ફરિયાદ આગળના સ્તરે મોકલાઈ."}
        else:  # info
            await request_info(db, grievance, actor_type=ActorType.OFFICER, actor_label=actor_label, provider=provider)
            result_ctx |= {"heading_en": "Information requested", "heading_gu": "માહિતી માંગી",
                           "detail_en": "The citizen has been asked for more information and the SLA clock is paused.",
                           "detail_gu": "નાગરિક પાસેથી માહિતી માંગી અને SLA ઘડિયાળ થોભાવી."}
        mark_used(db, row)
        db.commit()
    except InvalidTransitionError:
        db.rollback()
        result_ctx |= {"heading_en": "Already actioned", "heading_gu": "પહેલેથી કાર્યવાહી થઈ",
                       "detail_en": "This grievance was already updated through another action.",
                       "detail_gu": "આ ફરિયાદ પર પહેલેથી કાર્યવાહી થઈ ચૂકી છે."}

    grievance = db.get(Grievance, row.grievance_id)
    result_ctx["grievance"] = grievance
    return templates.TemplateResponse(request, "actions/result.html", result_ctx)
