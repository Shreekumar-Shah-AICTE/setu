"""Admin console (HTTP Basic).

Includes the signature Decision Trace panel and the active-learning review queue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import charts
from app.active_learning import apply_correction, counters
from app.classification.lexical import invalidate_index
from app.classification.semantic import recompute_department_centroid
from app.config import BASE_DIR, get_settings
from app.db import get_db
from app.email.base import get_email_provider
from app.llm.factory import get_llm_client
from app.models import (
    ClassificationTrace,
    Department,
    EvalRun,
    Grievance,
    GrievanceEvent,
    Keyword,
    Officer,
    ReviewQueue,
    SLAPolicy,
)
from app.reference import GUJARAT_DISTRICTS
from app.runtime_config import all_settings, get_classification_config, set_value
from app.security.auth import require_admin
from app.state import TERMINAL_STATUSES, Status
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

PAGE_SIZE = 25
_TERMINAL = {s.value for s in TERMINAL_STATUSES}


def _dept_colors(db: Session) -> dict[str, str]:
    codes = list(db.scalars(select(Department.code).order_by(Department.code)))
    return {code: charts.PALETTE[i % len(charts.PALETTE)] for i, code in enumerate(codes)}


async def _provider_badge() -> dict:
    client = get_llm_client()
    try:
        health = await client.health()
        return {"name": health.provider, "healthy": health.healthy, "degraded": health.degraded}
    except Exception as exc:  # pragma: no cover
        return {"name": client.name, "healthy": False, "degraded": True, "detail": str(exc)}


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    total = db.scalar(select(func.count()).select_from(Grievance)) or 0
    resolved = db.scalar(select(func.count()).select_from(Grievance).where(Grievance.status.in_(["RESOLVED", "CLOSED"]))) or 0
    open_count = db.scalar(select(func.count()).select_from(Grievance).where(Grievance.status.notin_(list(_TERMINAL)))) or 0
    overdue = db.scalar(
        select(func.count()).select_from(Grievance).where(
            Grievance.sla_due_at.is_not(None), Grievance.sla_due_at < now,
            Grievance.status.notin_(list(_TERMINAL)),
        )
    ) or 0
    today = db.scalar(
        select(func.count()).select_from(Grievance).where(Grievance.created_at >= now - timedelta(days=1))
    ) or 0
    escalations_24h = db.scalar(
        select(func.count()).select_from(GrievanceEvent).where(
            GrievanceEvent.event_type == "escalated", GrievanceEvent.created_at >= now - timedelta(days=1)
        )
    ) or 0
    review_pending = db.scalar(select(func.count()).select_from(ReviewQueue).where(ReviewQueue.resolved_at.is_(None))) or 0

    dept_counts = db.execute(
        select(Department.code, func.count(Grievance.id))
        .join(Grievance, Grievance.department_id == Department.id)
        .group_by(Department.code).order_by(func.count(Grievance.id).desc())
    ).all()
    donut_svg = charts.donut([(c, n) for c, n in dept_counts if n])

    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "total": total, "open": open_count, "overdue": overdue, "resolved": resolved,
        "today": today, "escalations_24h": escalations_24h, "review_pending": review_pending,
        "donut_svg": donut_svg, "provider": provider, "active": "dashboard",
    })


@router.get("/grievances", response_class=HTMLResponse)
async def grievances(
    request: Request, db: Session = Depends(get_db),
    department: str = "", status: str = "", urgency: str = "", level: str = "",
    district: str = "", q: str = "", page: int = 1,
):
    stmt = select(Grievance)
    if department:
        stmt = stmt.join(Department, Grievance.department_id == Department.id).where(Department.code == department)
    if status:
        stmt = stmt.where(Grievance.status == status)
    if urgency:
        stmt = stmt.where(Grievance.urgency == urgency)
    if level:
        stmt = stmt.where(Grievance.current_level == level)
    if district:
        stmt = stmt.where(Grievance.citizen_district == district)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Grievance.subject.like(like)) | (Grievance.body_raw.like(like)) | (Grievance.ref_no.like(like)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = max(1, page)
    rows = list(db.scalars(
        stmt.order_by(Grievance.created_at.desc()).limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)
    ))
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/grievances.html", {
        "rows": rows, "total": total, "page": page, "page_size": PAGE_SIZE,
        "pages": (total + PAGE_SIZE - 1) // PAGE_SIZE,
        "departments": list(db.scalars(select(Department).order_by(Department.code))),
        "districts": GUJARAT_DISTRICTS,
        "filters": {"department": department, "status": status, "urgency": urgency, "level": level, "district": district, "q": q},
        "statuses": [s.value for s in Status], "provider": provider, "active": "grievances",
    })


@router.get("/grievances/{ref_no}", response_class=HTMLResponse)
async def grievance_detail(ref_no: str, request: Request, db: Session = Depends(get_db)):
    grievance = db.scalar(select(Grievance).where(Grievance.ref_no == ref_no))
    if grievance is None:
        return templates.TemplateResponse(request, "public/not_found.html", {"ref_no": ref_no}, status_code=404)
    trace = db.scalar(select(ClassificationTrace).where(ClassificationTrace.grievance_id == grievance.id))
    colors = _dept_colors(db)

    trace_html = {}
    if trace:
        ordered_codes = sorted((trace.lexical_scores or {}).keys())
        lex_pairs = [(c, (trace.lexical_scores or {}).get(c, 0.0)) for c in ordered_codes]
        sem_pairs = [(c, (trace.semantic_scores or {}).get(c, 0.0)) for c in ordered_codes]
        fused_pairs = [(c, (trace.fused_scores or {}).get(c, 0.0)) for c in ordered_codes]
        cfg = get_classification_config(db)
        trace_html = {
            "highlight": charts.highlight_keywords(trace.normalized_text or "", trace.lexical_hits or [], colors),
            "lexical_svg": charts.hbar(lex_pairs, maxv=1.0),
            "semantic_svg": charts.hbar(sem_pairs, maxv=1.0, color="#8e44ad"),
            "fused_svg": charts.threshold_hbar(fused_pairs, cfg.confidence_high, maxv=max(1.0, max((v for _, v in fused_pairs), default=1.0))),
        }

    events = list(db.scalars(
        select(GrievanceEvent).where(GrievanceEvent.grievance_id == grievance.id).order_by(GrievanceEvent.created_at)
    ))
    sent_emails = [e for e in events if e.event_type == "email_sent"]
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/detail.html", {
        "g": grievance, "trace": trace, "trace_html": trace_html, "events": events,
        "sent_emails": sent_emails, "colors": colors, "provider": provider, "active": "grievances",
    })


@router.get("/review", response_class=HTMLResponse)
async def review_queue(request: Request, db: Session = Depends(get_db)):
    items = list(db.scalars(
        select(ReviewQueue).where(ReviewQueue.resolved_at.is_(None)).order_by(ReviewQueue.created_at.desc())
    ))
    rows = []
    for item in items:
        grievance = db.get(Grievance, item.grievance_id)
        rows.append({"item": item, "g": grievance})
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/review.html", {
        "rows": rows, "departments": list(db.scalars(select(Department).order_by(Department.code))),
        "counters": counters(db), "provider": provider, "active": "review",
    })


@router.post("/review/{review_id}/correct")
async def review_correct(review_id: str, request: Request, db: Session = Depends(get_db),
                         corrected_code: str = Form(...)):
    item = db.get(ReviewQueue, review_id)
    if item is not None and item.resolved_at is None:
        await apply_correction(db, item, corrected_code, client=get_llm_client(), provider=get_email_provider())
        db.commit()
    return RedirectResponse(url="/admin/review", status_code=303)


@router.get("/departments", response_class=HTMLResponse)
async def departments_page(request: Request, db: Session = Depends(get_db)):
    depts = list(db.scalars(select(Department).order_by(Department.code)))
    dept_rows = []
    for d in depts:
        kws = list(db.scalars(select(Keyword).where(Keyword.department_id == d.id).order_by(Keyword.source, Keyword.term)))
        dept_rows.append({"d": d, "keywords": kws})
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/departments.html", {
        "dept_rows": dept_rows, "provider": provider, "active": "departments",
    })


@router.post("/departments/keyword/add")
async def keyword_add(request: Request, db: Session = Depends(get_db),
                      department_id: str = Form(...), term: str = Form(...), weight: float = Form(1.0)):
    from app.classification.normalize import to_folded

    term = term.strip()
    if term:
        db.add(Keyword(department_id=department_id, term=term, term_normalized=to_folded(term),
                       token_count=len(term.split()), weight=weight, source="learned", is_active=True))
        db.flush()
        invalidate_index()
        dept = db.get(Department, department_id)
        await recompute_department_centroid(db, get_llm_client(), dept)
        db.commit()
    return RedirectResponse(url="/admin/departments", status_code=303)


@router.post("/departments/keyword/{keyword_id}/toggle")
async def keyword_toggle(keyword_id: str, db: Session = Depends(get_db)):
    kw = db.get(Keyword, keyword_id)
    if kw:
        kw.is_active = not kw.is_active
        db.flush()
        invalidate_index()
        db.commit()
    return RedirectResponse(url="/admin/departments", status_code=303)


@router.post("/departments/keyword/{keyword_id}/weight")
async def keyword_weight(keyword_id: str, db: Session = Depends(get_db), weight: float = Form(...)):
    kw = db.get(Keyword, keyword_id)
    if kw:
        kw.weight = weight
        db.flush()
        invalidate_index()
        db.commit()
    return RedirectResponse(url="/admin/departments", status_code=303)


@router.get("/officers", response_class=HTMLResponse)
async def officers_page(request: Request, db: Session = Depends(get_db)):
    officers = list(db.scalars(select(Officer).join(Department).order_by(Department.code, Officer.level)))
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/officers.html", {
        "officers": officers, "departments": list(db.scalars(select(Department).order_by(Department.code))),
        "provider": provider, "active": "officers",
    })


@router.post("/officers/add")
async def officer_add(db: Session = Depends(get_db), department_id: str = Form(...), name: str = Form(...),
                      designation_en: str = Form(""), designation_gu: str = Form(""), email: str = Form(...),
                      phone: str = Form(""), level: str = Form("L1"), district: str = Form("")):
    db.add(Officer(department_id=department_id, name=name, designation_en=designation_en or name,
                   designation_gu=designation_gu or name, email=email, phone=phone or None,
                   level=level, district=district or None, is_active=True))
    db.commit()
    return RedirectResponse(url="/admin/officers", status_code=303)


@router.post("/officers/{officer_id}/toggle")
async def officer_toggle(officer_id: str, db: Session = Depends(get_db)):
    o = db.get(Officer, officer_id)
    if o:
        o.is_active = not o.is_active
        db.commit()
    return RedirectResponse(url="/admin/officers", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    cfg = get_classification_config(db)
    policies = list(db.scalars(select(SLAPolicy).where(SLAPolicy.department_id.is_(None)).order_by(SLAPolicy.level)))
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/settings.html", {
        "cfg": cfg, "policies": policies, "all_settings": all_settings(db),
        "provider": provider, "active": "settings",
        "time_scale": get_settings().sla_time_scale,
    })


@router.post("/settings")
async def settings_save(
    db: Session = Depends(get_db),
    classify_alpha: float = Form(...), confidence_high: float = Form(...), margin_min: float = Form(...),
    other_threshold: float = Form(...), review_threshold: float = Form(...),
    sla_l1: float = Form(...), sla_l2: float = Form(...), sla_l3: float = Form(...),
):
    set_value(db, "classify_alpha", classify_alpha)
    set_value(db, "confidence_high", confidence_high)
    set_value(db, "margin_min", margin_min)
    set_value(db, "other_threshold", other_threshold)
    set_value(db, "review_threshold", review_threshold)
    for level, hours in (("L1", sla_l1), ("L2", sla_l2), ("L3", sla_l3)):
        policy = db.scalar(select(SLAPolicy).where(SLAPolicy.department_id.is_(None), SLAPolicy.level == level))
        if policy:
            policy.hours = hours
    db.commit()
    return RedirectResponse(url="/admin/settings", status_code=303)


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    dept_counts = db.execute(
        select(Department.code, func.count(Grievance.id))
        .join(Grievance, Grievance.department_id == Department.id)
        .group_by(Department.code).order_by(func.count(Grievance.id).desc())
    ).all()
    status_counts = db.execute(select(Grievance.status, func.count()).group_by(Grievance.status)).all()

    # 30-day intake trend.
    trend = []
    for i in range(29, -1, -1):
        day = (now - timedelta(days=i)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        n = db.scalar(select(func.count()).select_from(Grievance).where(
            Grievance.created_at >= start, Grievance.created_at < end)) or 0
        trend.append((day.isoformat(), n))

    # Mean resolution time (hours) by department.
    resolved = db.execute(
        select(Department.code, Grievance.created_at, Grievance.resolved_at)
        .join(Grievance, Grievance.department_id == Department.id)
        .where(Grievance.resolved_at.is_not(None))
    ).all()
    agg: dict[str, list[float]] = {}
    for code, created, resolved_at in resolved:
        if created and resolved_at:
            hrs = (resolved_at - created).total_seconds() / 3600.0
            agg.setdefault(code, []).append(hrs)
    mrt = [(code, round(sum(v) / len(v), 1)) for code, v in sorted(agg.items())]

    total = db.scalar(select(func.count()).select_from(Grievance)) or 1
    escalated = db.scalar(select(func.count(func.distinct(GrievanceEvent.grievance_id)))
                          .where(GrievanceEvent.event_type == "escalated")) or 0
    resolved_n = db.scalar(select(func.count()).select_from(Grievance).where(Grievance.status.in_(["RESOLVED", "CLOSED"]))) or 0
    on_time = db.scalar(select(func.count()).select_from(Grievance).where(
        Grievance.status.in_(["RESOLVED", "CLOSED"]), Grievance.resolved_at.is_not(None),
        Grievance.sla_due_at.is_not(None), Grievance.resolved_at <= Grievance.sla_due_at)) or 0

    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/analytics.html", {
        "dept_svg": charts.hbar([(c, n) for c, n in dept_counts], maxv=None, value_fmt="{:.0f}"),
        "status_svg": charts.donut([(s, n) for s, n in status_counts]),
        "trend_svg": charts.line(trend),
        "mrt_svg": charts.hbar(mrt, maxv=None, value_fmt="{:.1f}h") if mrt else "",
        "escalation_rate": round(100 * escalated / total, 1),
        "sla_compliance": round(100 * on_time / resolved_n, 1) if resolved_n else 0.0,
        "resolved_n": resolved_n, "total": total, "provider": provider, "active": "analytics",
    })


@router.get("/evaluation", response_class=HTMLResponse)
async def evaluation_page(request: Request, db: Session = Depends(get_db)):
    latest = {}
    for run in db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(30)):
        cfg = (run.config or {}).get("config", run.run_name)
        if cfg not in latest:
            latest[cfg] = run
    report_exists = (BASE_DIR / "deliverables" / "evaluation_report.html").exists()
    provider = await _provider_badge()
    return templates.TemplateResponse(request, "admin/evaluation.html", {
        "runs": sorted(latest.values(), key=lambda r: r.run_name), "report_exists": report_exists,
        "provider": provider, "active": "evaluation",
    })


@router.get("/evaluation/report", response_class=HTMLResponse)
async def evaluation_report(request: Request):
    path = BASE_DIR / "deliverables" / "evaluation_report.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse("<p>No report yet. Run the evaluation.</p>", status_code=404)


@router.post("/evaluation/run")
async def evaluation_run(db: Session = Depends(get_db)):
    from app.evaluation.report import run_and_report

    await run_and_report()
    return RedirectResponse(url="/admin/evaluation", status_code=303)
