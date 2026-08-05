"""Capture UI screenshots with headless Chromium (a dev tool, not shipped runtime).

Starts the SETU server against the seeded/simulated database, drives it with
Playwright, and writes PNGs to docs/screenshots/. Requires the (disposable)
Playwright Chromium binary:  python -m playwright install chromium
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"
ADMIN = ("admin", "setu-admin")


def _pick_refs() -> tuple[str | None, str | None]:
    """Return (ref_with_arbiter_trace, any_escalated_ref)."""
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import ClassificationTrace, Grievance

    with session_scope() as db:
        trace_ref = None
        t = db.scalar(select(ClassificationTrace).where(ClassificationTrace.arbiter_invoked.is_(True)))
        if t:
            g = db.get(Grievance, t.grievance_id)
            trace_ref = g.ref_no if g else None
        if trace_ref is None:
            g = db.scalar(select(Grievance).where(Grievance.department_id.is_not(None)))
            trace_ref = g.ref_no if g else None
        esc = db.scalar(select(Grievance).where(Grievance.status == "ESCALATED_L2"))
        return trace_ref, (esc.ref_no if esc else trace_ref)


def _start_server() -> subprocess.Popen:
    env = dict(os.environ)
    env.update({"SCHEDULER_ENABLED": "false", "PUBLIC_BASE_URL": BASE, "LLM_PROVIDER": "mock",
                "EMAIL_PROVIDER": "console"})
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            if httpx.get(f"{BASE}/health", timeout=1).status_code == 200:
                return proc
        except Exception:
            time.sleep(0.3)
    return proc


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    trace_ref, esc_ref = _pick_refs()
    proc = _start_server()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        proc.terminate()
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                                  http_credentials={"username": ADMIN[0], "password": ADMIN[1]})
        page = ctx.new_page()

        def shot(name):
            page.screenshot(path=str(SHOTS / name), full_page=True)
            print("captured", name)

        page.goto(f"{BASE}/", wait_until="networkidle")
        shot("01_landing.png")

        page.fill("#citizen_name", "Nirav Chauhan")
        page.fill("#citizen_phone", "9876500011")
        page.select_option("#citizen_district", "Surat")
        page.fill("#subject", "ટ્રાન્સફોર્મર બળી ગયું")
        page.fill("#body", "અમારા ગામમાં છેલ્લા છ દિવસથી વીજળી નથી અને ટ્રાન્સફોર્મર બળી ગયું છે. પીજીવીસીએલ જવાબ આપતું નથી.")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        shot("02_confirmation.png")
        new_ref = page.inner_text("#refno").strip() if page.query_selector("#refno") else None

        page.goto(f"{BASE}/track/{new_ref or trace_ref}", wait_until="networkidle")
        shot("03_tracking.png")

        page.goto(f"{BASE}/admin", wait_until="networkidle")
        shot("04_admin_dashboard.png")

        page.goto(f"{BASE}/admin/grievances", wait_until="networkidle")
        shot("09_admin_grievances.png")

        if trace_ref:
            page.goto(f"{BASE}/admin/grievances/{trace_ref}", wait_until="networkidle")
            shot("05_grievance_detail.png")
            el = page.query_selector("xpath=//h2[contains(., 'Decision Trace')]/..")
            if el:
                el.screenshot(path=str(SHOTS / "06_decision_trace.png"))
                print("captured 06_decision_trace.png")

        page.goto(f"{BASE}/admin/review", wait_until="networkidle")
        shot("07_review_queue.png")

        page.goto(f"{BASE}/admin/evaluation/report", wait_until="networkidle")
        shot("08_evaluation_report.png")

        page.goto(f"{BASE}/admin/analytics", wait_until="networkidle")
        shot("11_admin_analytics.png")

        # Rendered officer email (open the newest HTML preview from the outbox).
        previews = sorted((ROOT / "outbox").glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True)
        if previews:
            page.goto(previews[0].as_uri(), wait_until="networkidle")
            shot("10_officer_email.png")

        browser.close()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    print("Screenshots written to", SHOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
