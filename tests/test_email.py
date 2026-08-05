"""Tests for email rendering, threading headers, .eml validity and dispatch."""
from __future__ import annotations

from email import message_from_bytes
from pathlib import Path
from types import SimpleNamespace

from app.classification.pipeline import intake_grievance
from app.email.base import OutboundEmail
from app.email.console import ConsoleEmailProvider
from app.email.render import render_officer_dispatch
from app.email.threading import new_message_id
from app.routing.dispatcher import dispatch_grievance, escalate_grievance
from app.state import ActorType


def _fake_context():
    grievance = SimpleNamespace(
        ref_no="SETU-20260101-ABC123", subject="વીજ સમસ્યા",
        body_raw="ગામમાં ટ્રાન્સફોર્મર બળી ગયું", citizen_district="Surat", citizen_name="Test",
    )
    department = SimpleNamespace(name_en="Energy", name_gu="ઊર્જા")
    officer = SimpleNamespace(name="Officer X", designation_en="Deputy Engineer", designation_gu="નાયબ ઈજનેર")
    return {
        "grievance": grievance, "department": department, "officer": officer,
        "confidence": 0.82, "urgency": "HIGH", "level": "L1", "deadline": "01 Jan 2026, 12:00 IST",
        "resolve_url": "http://x/action/RES", "escalate_url": "http://x/action/ESC",
        "info_url": "http://x/action/INF", "track_url": "http://x/track/SETU-20260101-ABC123",
        "urgent": False, "sla_hours": 6,
    }


def test_officer_email_renders_bilingual_with_buttons():
    html, text = render_officer_dispatch(_fake_context())
    assert "SETU-20260101-ABC123" in html and "SETU-20260101-ABC123" in text
    assert "નિરાકરણ થયું" in html  # Gujarati button label
    assert "http://x/action/RES" in html and "http://x/action/ESC" in text
    assert "Deputy Engineer" in html


async def test_console_provider_writes_valid_eml(tmp_outbox: Path):
    provider = ConsoleEmailProvider()
    root = new_message_id()
    msg = OutboundEmail(
        to=["officer@example.gov.in"], subject="[SETU-1] test", html_body="<b>hi</b>",
        text_body="hi", message_id=root, grievance_id="g1", kind="dispatch",
    )
    result = await provider.send(msg)
    assert result.ok and result.path
    eml = Path(result.path)
    assert eml.exists()
    parsed = message_from_bytes(eml.read_bytes())
    assert parsed["Message-ID"] == root
    assert parsed.is_multipart()
    subtypes = {p.get_content_subtype() for p in parsed.walk()}
    assert "plain" in subtypes and "html" in subtypes


async def test_threading_headers_on_reply(tmp_outbox: Path):
    provider = ConsoleEmailProvider()
    root = new_message_id()
    reply = OutboundEmail(
        to=["a@b.c"], subject="re", html_body="<i>x</i>", text_body="x",
        message_id=new_message_id(), in_reply_to=root, references=root, grievance_id="g2", kind="escalation",
    )
    result = await provider.send(reply)
    parsed = message_from_bytes(Path(result.path).read_bytes())
    assert parsed["In-Reply-To"] == root
    assert parsed["References"] == root


async def test_full_dispatch_and_forward(db):
    grievance, _ = await intake_grievance(
        db, citizen_name="Citizen", subject="વીજ સમસ્યા",
        body="અમારા ગામમાં ટ્રાન્સફોર્મર બળી ગયું અને અંધારપટ છે વીજપોલ તૂટેલો પીજીવીસીએલ",
        citizen_district="Surat",
    )
    provider = ConsoleEmailProvider()
    if grievance.status == "CLASSIFIED":
        res = await dispatch_grievance(db, grievance, provider=provider)
        assert res.officer is not None
        assert grievance.assigned_officer_id is not None
        assert grievance.status in {"ASSIGNED_L1", "ESCALATED_L2"}
        assert grievance.sla_due_at is not None
        # Three action tokens created for this grievance.
        from sqlalchemy import func, select

        from app.models import ActionToken
        n = db.scalar(select(func.count()).select_from(ActionToken).where(ActionToken.grievance_id == grievance.id))
        assert n == 3

        # Officer forwards to senior with a reason -> escalation.
        before = grievance.status
        await escalate_grievance(db, grievance, reason="Requires district-level intervention",
                                 actor_type=ActorType.OFFICER, actor_label="Officer X", provider=provider)
        assert grievance.status in {"ESCALATED_L2", "ESCALATED_L3"}
        assert grievance.status != before or before == "ESCALATED_L2"
