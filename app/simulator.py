"""The Time Machine — generate a realistic month of operational history.

    python -m app.cli simulate --days 30 --count 220 --seed 42

~220 grievances with backdated ``created_at`` following a weekday intake
pattern, all run through the real classification pipeline, with a realistic
outcome mix (≈55% resolved at L1, ≈25% escalated to L2, ≈8% reached L3, ≈7%
open and already past deadline so the scheduler fires within a minute, ≈5% in
the review queue, plus duplicate clusters and a few CRITICAL items). Events are
backdated coherently so timelines look real. Deterministic under ``--seed``.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.classification.pipeline import intake_grievance
from app.db import session_scope
from app.email.console import ConsoleEmailProvider
from app.models import (
    ActionToken,
    ClassificationTrace,
    Grievance,
    GrievanceEvent,
    ReviewQueue,
)
from app.reference import GUJARAT_DISTRICTS
from app.routing.directory import select_officer
from app.routing.dispatcher import _send_officer_email
from app.sla.engine import base_hours_for, next_level
from app.state import ActorType, Status, record_event, transition
from app.vectors import rebuild as rebuild_vectors

logger = logging.getLogger("setu.simulator")

DISTRICTS = [en for en, _ in GUJARAT_DISTRICTS]
NAMES = ["Ramesh Patel", "Sunita Desai", "Kiran Solanki", "Alpa Mehta", "Jignesh Shah",
         "Bhavna Trivedi", "Naresh Pandya", "Rekha Joshi", "Manoj Bhavsar", "Falguni Amin",
         "Dilip Vaghela", "Meena Rathod", "Ashok Makwana", "Nita Shah", "Bharat Rana"]

DEPT_TEXTS = [
    "છેલ્લા પાંચ દિવસથી વીજળી નથી અને ટ્રાન્સફોર્મર બળી ગયું છે પીજીવીસીએલ",
    "લો-વોલ્ટેજ અને વારંવાર વીજ કાપ થાય છે વીજ કંપની જવાબ આપતી નથી",
    "ખેડૂતોને યુરિયા ખાતર મળતું નથી અને એપીએમસી માર્કેટયાર્ડમાં ટેકાના ભાવે ખરીદી શરૂ થઈ નથી",
    "બિયારણ અને પીએમ કિસાન યોજના નો લાભ ખેડૂત ને મળ્યો નથી",
    "રાશન કાર્ડ પર અનાજ મળતું નથી પ્રાઈસ શોપ વાળા કહે છે પુરવઠો આવ્યો નથી",
    "ગેસ એજન્સી બે મહિનાથી સિલિન્ડર આપતી નથી",
    "મુખ્ય રસ્તા પર ટ્રાફિક સિગ્નલ બંધ છે અને રોજ ટ્રાફિક જામ થાય છે પોલીસને જાણ",
    "ઓવરલોડિંગ વાહન રોડ પર દોડે છે અને ક્રાઇમ વધ્યો છે પોલીસ",
    "જીઆઇડીસી વિસ્તારમાં કારખાના ને પ્લોટ ફાળવણી ઔદ્યોગિક એકમો",
    "નદીમાં ગેરકાયદે રેતી ખનન ચાલે છે ખાણ માફિયા રાત્રે ટ્રક ભરે છે",
    "કુટિર ઉદ્યોગ માટે માનવ કલ્યાણ યોજના હેઠળ ટુલકીટ મળી નથી",
    "ગામની બેંક નું એટીએમ છેલ્લા એક મહિનાથી બંધ છે નાણા વિભાગ",
    "કેમિકલ કંપની અભયારણ પાસે રસાયણિક કચરો ઠાલવે છે પર્યાવરણ ને નુકસાન",
    "માછીમારોને બોક્સ ફિશિંગ ની પરવાનગી નથી ઝીંગા તળાવ સહાય બાકી ફિશરિઝ",
    "મત્સ્યોદ્યોગ વિભાગ માં અરજી છ મહિનાથી પેન્ડિંગ છે માછીમાર",
    "Amara gaam ma light nathi aavti, transformer bali gayu, PGVCL ne kahyu",
    "Khedut ne urea khatar nathi maltu, apmc marketyard band che",
    "કારખાનાની ચીમનીમાંથી ધૂમાડો અને કેમિકલ્સ થી પર્યાવરણ ને નુકસાન",
]
CRITICAL_TEXTS = [
    "વીજપોલનો તાર તૂટીને રસ્તા પર પડ્યો છે બાળકોને કરંટ લાગવાનું જોખમ છે તાત્કાલિક",
    "કારખાનામાં આગ લાગી છે અને ગેસ લીકેજ થઈ રહ્યું છે તાત્કાલિક કાર્યવાહી",
    "દૂષિત પાણી થી ગામમાં લોકો બીમાર પડ્યા છે હોસ્પિટલ",
]
AMBIGUOUS_TEXTS = [
    "Primary school has no teacher in the village since last year",
    "ગામમાં પીવાના પાણી ની લાઇન બંધ છે નળ માં પાણી નથી",
    "જમીન ના ૭/૧૨ ના ઉતારા અને મહેસૂલ રેકોર્ડ માં ભૂલ છે",
    "વૃદ્ધ પેન્શન ત્રણ મહિનાથી બેંક ખાતામાં જમા થયું નથી",
]
DUP_TEXT = "અમારા ગામમાં ટ્રાન્સફોર્મર બળી ગયું છે અને છેલ્લા દિવસોથી અંધારપટ છે પીજીવીસીએલ"

# Varied closing details so non-cluster grievances are genuinely distinct.
DETAILS = [
    "અમે અનેક વાર રજૂઆત કરી છે પણ કોઈ કાર્યવાહી થઈ નથી",
    "સ્થાનિક કચેરીએ ધ્યાન આપ્યું નથી અને લોકો પરેશાન છે",
    "કૃપા કરી તાત્કાલિક યોગ્ય કાર્યવાહી કરવા વિનંતી છે",
    "ગત મહિનાની અરજી નો હજુ સુધી કોઈ જવાબ મળ્યો નથી",
    "આ સમસ્યા છેલ્લા કેટલાક અઠવાડિયાથી ચાલુ છે",
    "ગામના સરપંચ મારફતે પણ જાણ કરવામાં આવી છે",
    "વારંવાર ફોન કરવા છતાં કોઈ ઉકેલ આવ્યો નથી",
    "આના કારણે રોજિંદા જીવન પર ગંભીર અસર થઈ રહી છે",
    "તંત્ર દ્વારા સત્વરે નિરાકરણ લાવવા માંગ છે",
    "સ્થાનિક રહેવાસીઓ વતી આ ફરિયાદ રજૂ કરું છું",
]


def _clear(db):
    for model in (ActionToken, ReviewQueue, ClassificationTrace, GrievanceEvent):
        db.execute(delete(model))
    db.execute(delete(Grievance))
    db.flush()


def _weekday_weight(d) -> float:
    return 0.4 if d.weekday() == 6 else (0.7 if d.weekday() == 5 else 1.0)


def _backdate_initial(grievance, t0: datetime):
    events = sorted(grievance.events, key=lambda e: e.created_at)
    for i, ev in enumerate(events):
        ev.created_at = t0 + timedelta(seconds=45 * i)
    grievance.created_at = t0
    grievance.updated_at = t0 + timedelta(seconds=45 * max(1, len(events)))


def _apply(db, grievance, status: Status, when: datetime, *, event_type, note=None,
           actor=ActorType.SYSTEM, payload=None):
    ev = transition(db, grievance, status, event_type=event_type, actor_type=actor, note=note, payload=payload)
    ev.created_at = when
    grievance.updated_at = when
    if status in (Status.ASSIGNED_L1, Status.ESCALATED_L2) and grievance.assigned_at:
        grievance.assigned_at = when
    if status == Status.RESOLVED:
        grievance.resolved_at = when
    if status == Status.CLOSED:
        grievance.closed_at = when
    db.flush()
    return ev


async def _assign(db, grievance, level, when, provider, *, send_email):
    officer = select_officer(db, grievance.department_id, level, grievance.citizen_district)
    if officer is None:
        return None
    grievance.assigned_officer_id = officer.id
    if grievance.root_message_id is None:
        from app.email.threading import new_message_id
        grievance.root_message_id = new_message_id()
    hours, _ = base_hours_for(db, level, grievance.department_id)
    factor = {"CRITICAL": 0.25, "HIGH": 0.5, "NORMAL": 1.0, "LOW": 1.5}.get(grievance.urgency, 1.0)
    grievance.sla_due_at = when + timedelta(hours=hours * factor)
    grievance.assigned_at = when
    target = Status.ESCALATED_L2 if level == "L2" else Status.ASSIGNED_L1
    _apply(db, grievance, target, when, event_type="assigned",
           note=f"Assigned to {officer.designation_en} ({level})",
           payload={"officer_id": officer.id, "level": level})
    if send_email:
        await _send_officer_email(db, grievance, officer, kind="dispatch", provider=provider)
    return officer


async def _escalate(db, grievance, to_level, when, provider, reason, actor=ActorType.SYSTEM):
    officer = select_officer(db, grievance.department_id, to_level, grievance.citizen_district)
    if officer:
        grievance.assigned_officer_id = officer.id
    hours, _ = base_hours_for(db, to_level, grievance.department_id)
    grievance.sla_due_at = when + timedelta(hours=hours)
    target = Status.ESCALATED_L2 if to_level == "L2" else Status.ESCALATED_L3
    _apply(db, grievance, target, when, event_type="escalated", actor=actor, note=reason,
           payload={"to_level": to_level, "reason": reason})
    if officer:
        await _send_officer_email(db, grievance, officer, kind="escalation", provider=provider)


def _pick_time(rng, now, days) -> datetime:
    for _ in range(10):
        offset = rng.random() * days
        day = now - timedelta(days=offset)
        if rng.random() <= _weekday_weight(day):
            hour = rng.choices(range(9, 19), weights=[2, 4, 5, 5, 4, 3, 4, 5, 4, 2])[0]
            return day.replace(hour=hour, minute=rng.randint(0, 59), second=0, microsecond=0)
    return now - timedelta(days=rng.random() * days)


async def run_simulation(*, days: int = 30, count: int = 220, seed: int = 42, reset: bool = True) -> dict:
    rng = random.Random(seed)
    provider = ConsoleEmailProvider()
    now = datetime.now(timezone.utc)
    summary = {"created": 0, "resolved": 0, "escalated_l2": 0, "escalated_l3": 0,
               "overdue": 0, "review": 0, "duplicates": 0, "critical": 0}

    # Outcome plan.
    plan = (["resolved"] * round(count * 0.55) + ["l2"] * round(count * 0.25)
            + ["l3"] * round(count * 0.08) + ["overdue"] * round(count * 0.07)
            + ["review"] * round(count * 0.05))
    plan += ["resolved"] * (count - len(plan))
    plan = plan[:count]
    rng.shuffle(plan)

    with session_scope() as db:
        if reset:
            _clear(db)

        # A few duplicate clusters up front (same district, near-identical text).
        for k in range(6):
            district = DISTRICTS[k % len(DISTRICTS)]
            t0 = _pick_time(rng, now, days)
            g1, _ = await intake_grievance(db, citizen_name=rng.choice(NAMES), subject="વીજ સમસ્યા",
                                           body=DUP_TEXT, citizen_district=district,
                                           citizen_phone="9" + str(rng.randint(100000000, 999999999)),
                                           created_at=t0)
            _backdate_initial(g1, t0)
            if g1.status == Status.CLASSIFIED.value:
                await _assign(db, g1, "L1", t0 + timedelta(minutes=20), provider, send_email=False)
            g2, _ = await intake_grievance(db, citizen_name=rng.choice(NAMES), subject="વીજ સમસ્યા",
                                           body=DUP_TEXT + " ફરી", citizen_district=district,
                                           citizen_phone="9" + str(rng.randint(100000000, 999999999)),
                                           created_at=t0 + timedelta(hours=6))
            _backdate_initial(g2, t0 + timedelta(hours=6))
            if g2.status == Status.DUPLICATE.value:
                summary["duplicates"] += 1
            summary["created"] += 2
        db.flush()
        rebuild_vectors(db)

        for i in range(count):
            bucket = plan[i]
            t0 = _pick_time(rng, now, days)
            if bucket == "review":
                text = rng.choice(AMBIGUOUS_TEXTS)
            elif rng.random() < 0.06:
                text = rng.choice(CRITICAL_TEXTS)
            else:
                text = DEPT_TEXTS[i % len(DEPT_TEXTS)]
            district = DISTRICTS[rng.randint(0, len(DISTRICTS) - 1)]
            # Make non-cluster grievances unique so only the intended duplicate
            # clusters trip the dedupe detector.
            ward = rng.randint(1, 60)
            detail = DETAILS[(i * 7 + ward) % len(DETAILS)]
            body = f"{text}. {detail}. {district} જિલ્લો, વોર્ડ {ward}, અરજી ક્રમ {i}."

            grievance, _ = await intake_grievance(
                db, citizen_name=rng.choice(NAMES), subject=text[:40], body=body,
                citizen_district=district, citizen_phone="9" + str(rng.randint(100000000, 999999999)),
                citizen_email=(f"citizen{i}@example.com" if rng.random() < 0.5 else None),
                created_at=t0,
            )
            _backdate_initial(grievance, t0)
            summary["created"] += 1

            if grievance.status == Status.DUPLICATE.value:
                summary["duplicates"] += 1
                continue
            if grievance.status == Status.NEEDS_REVIEW.value or bucket == "review":
                summary["review"] += 1
                continue
            if grievance.urgency == "CRITICAL":
                summary["critical"] += 1

            level = "L2" if grievance.urgency == "CRITICAL" else "L1"
            assign_at = t0 + timedelta(minutes=rng.randint(10, 90))
            send = rng.random() < 0.2 or grievance.urgency == "CRITICAL" or bucket in ("overdue", "l2", "l3")
            await _assign(db, grievance, level, assign_at, provider, send_email=send)

            if bucket == "resolved":
                ack = assign_at + timedelta(hours=rng.uniform(1, 8))
                resolve = ack + timedelta(hours=rng.uniform(2, 40))
                if resolve < now:
                    ack_status = Status.ACKNOWLEDGED_L2 if level == "L2" else Status.ACKNOWLEDGED_L1
                    _apply(db, grievance, ack_status, ack, event_type="acknowledged", actor=ActorType.OFFICER)
                    grievance.resolution_note = "Issue attended and resolved by the field team."
                    _apply(db, grievance, Status.RESOLVED, resolve, event_type="resolved", actor=ActorType.OFFICER)
                    summary["resolved"] += 1
                    if rng.random() < 0.4 and resolve + timedelta(days=7) < now:
                        _apply(db, grievance, Status.CLOSED, resolve + timedelta(days=7), event_type="closed")
                else:
                    summary["overdue"] += 1
            elif bucket == "l2":
                to = next_level(grievance.current_level or "L1")
                if to:
                    esc = assign_at + timedelta(hours=rng.uniform(20, 80))
                    reason = rng.choice(["SLA breach at L1", "Forwarded by junior: needs district sanction"])
                    actor = ActorType.OFFICER if "Forwarded" in reason else ActorType.SYSTEM
                    await _escalate(db, grievance, to, esc, provider, reason, actor=actor)
                    summary["escalated_l2"] += 1
                    if rng.random() < 0.6:
                        resolve = esc + timedelta(hours=rng.uniform(4, 40))
                        if resolve < now:
                            grievance.resolution_note = "Resolved at district level after escalation."
                            _apply(db, grievance, Status.RESOLVED, resolve, event_type="resolved", actor=ActorType.OFFICER)
                            summary["resolved"] += 1
            elif bucket == "l3":
                esc_time = assign_at + timedelta(hours=rng.uniform(20, 60))
                while True:
                    to = next_level(grievance.current_level or "L1")
                    if to is None:
                        break
                    await _escalate(db, grievance, to, esc_time, provider, f"SLA breach -> {to}")
                    if to == "L2":
                        summary["escalated_l2"] += 1
                    elif to == "L3":
                        summary["escalated_l3"] += 1
                    esc_time = esc_time + timedelta(hours=rng.uniform(20, 48))
                if rng.random() < 0.5:
                    resolve = esc_time + timedelta(hours=rng.uniform(4, 24))
                    if resolve < now:
                        grievance.resolution_note = "Resolved at state level."
                        _apply(db, grievance, Status.RESOLVED, resolve, event_type="resolved", actor=ActorType.OFFICER)
                        summary["resolved"] += 1
            elif bucket == "overdue":
                # Already past deadline and still open -> the scheduler will escalate it live.
                grievance.sla_due_at = now - timedelta(minutes=rng.randint(2, 240))
                db.flush()
                summary["overdue"] += 1

        rebuild_vectors(db)

    logger.info("Simulation summary: %s", summary)
    return summary
