"""HTTP tests for the citizen portal (and, later, the JSON API)."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

GUJARATI_ENERGY = (
    "અમારા ગામમાં છેલ્લા પાંચ દિવસથી ટ્રાન્સફોર્મર બળી ગયું છે અને અંધારપટ છે. "
    "પીજીવીસીએલને ફરિયાદ કરી પણ કોઈ જવાબ મળ્યો નથી."
)


def test_landing_form_renders():
    r = client.get("/")
    assert r.status_code == 200
    assert "ફરિયાદ" in r.text
    assert "Surat" in r.text  # district dropdown present


def test_submit_validation_errors():
    r = client.post("/submit", data={"citizen_name": "", "citizen_phone": "123", "body": "short"},
                    follow_redirects=False)
    assert r.status_code == 400
    assert "mobile" in r.text.lower() or "મોબાઈલ" in r.text


def test_submit_classify_dispatch_and_track():
    r = client.post(
        "/submit",
        data={
            "citizen_name": "Test Citizen", "citizen_phone": "9876543210", "citizen_email": "",
            "citizen_district": "Surat", "subject": "વીજ સમસ્યા", "body": GUJARATI_ENERGY,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    ref = location.rsplit("/", 1)[-1]
    assert ref.startswith("SETU-")

    confirmation = client.get(location)
    assert confirmation.status_code == 200
    assert ref in confirmation.text

    track = client.get(f"/track/{ref}")
    assert track.status_code == 200
    assert "Submitted" in track.text or "ફરિયાદ મળી" in track.text
    # An officer email should have been written to the outbox.
    from app.config import get_settings

    emls = list(get_settings().outbox_path.glob("*.eml"))
    assert emls, "expected at least one officer email in outbox"


def test_track_not_found():
    r = client.get("/track/SETU-00000000-ZZZZZZ")
    assert r.status_code == 404
    assert "No grievance found" in r.text or "મળી નથી" in r.text


AUTH = ("admin", "setu-admin")


def test_api_create_get_classify_stats_health():
    r = client.post("/api/v1/grievances", json={
        "citizen_name": "Aarav Patel", "citizen_phone": "9876543210", "citizen_district": "Bhavnagar",
        "subject": "વીજળી ની ફરિયાદ",
        "body": "ભાવનગર જિલ્લામાં લો-વોલ્ટેજ અને વારંવાર વીજ કાપ થાય છે, વીજ કંપની જવાબ આપતી નથી.",
    })
    assert r.status_code == 200
    ref = r.json()["ref_no"]
    assert r.json()["department"] == "ENERGY"

    got = client.get(f"/api/v1/grievances/{ref}")
    assert got.status_code == 200 and got.json()["ref_no"] == ref

    cl = client.post("/api/v1/classify", json={"subject": "", "body": "ખેડૂત ને યુરિયા ખાતર નથી"})
    assert cl.status_code == 200 and cl.json()["department"] == "AGRICULTURE"

    assert client.get("/api/v1/departments").json()[0]["code"]
    assert client.get("/api/v1/stats").json()["total"] >= 1
    assert client.get("/api/v1/health").json()["provider"]["name"] == "mock"


def test_admin_requires_auth():
    assert client.get("/admin").status_code == 401


def test_admin_pages_render_with_auth():
    r = client.post("/api/v1/grievances", json={
        "citizen_name": "Meera Shah", "citizen_phone": "9812345670", "citizen_district": "Rajkot",
        "subject": "વીજ", "body": GUJARATI_ENERGY,
    })
    ref = r.json()["ref_no"]
    for path in ["/admin", "/admin/grievances", "/admin/review", "/admin/departments",
                 "/admin/officers", "/admin/settings", "/admin/analytics", "/admin/evaluation"]:
        assert client.get(path, auth=AUTH).status_code == 200, path
    detail = client.get(f"/admin/grievances/{ref}", auth=AUTH)
    assert detail.status_code == 200
    assert "Decision Trace" in detail.text


def test_active_learning_correction_updates_department_and_counter():
    import asyncio

    from sqlalchemy import select

    from app.active_learning import counters
    from app.classification.lexical import invalidate_index
    from app.classification.semantic import compute_centroids
    from app.db import session_scope
    from app.llm.factory import get_llm_client
    from app.models import GoldenSample, Grievance, Keyword, ReviewQueue

    # An English grievance with no keyword hits lands in OTHER + review queue.
    r = client.post("/api/v1/grievances", json={
        "citizen_name": "Ravi Kumar", "citizen_phone": "9800000001", "citizen_district": "Anand",
        "subject": "School issue", "body": "Primary school has no teacher in our village since last year",
    })
    ref = r.json()["ref_no"]

    with session_scope() as db:
        before = counters(db)["corrections"]
        g = db.scalar(select(Grievance).where(Grievance.ref_no == ref))
        item = db.scalar(select(ReviewQueue).where(ReviewQueue.grievance_id == g.id, ReviewQueue.resolved_at.is_(None)))
        assert item is not None
        review_id = item.id

    try:
        resp = client.post(f"/admin/review/{review_id}/correct", data={"corrected_code": "ENERGY"},
                           auth=AUTH, follow_redirects=False)
        assert resp.status_code == 303
        got = client.get(f"/api/v1/grievances/{ref}").json()
        assert got["department"] == "ENERGY"
        with session_scope() as db:
            assert counters(db)["corrections"] == before + 1
    finally:
        # Restore shared test-DB state so centroids don't leak into other tests.
        with session_scope() as db:
            for gs in db.scalars(select(GoldenSample).where(GoldenSample.notes.like("absorbed from%"))):
                db.delete(gs)
            for kw in db.scalars(select(Keyword).where(Keyword.source == "learned")):
                db.delete(kw)
            db.flush()
            asyncio.run(compute_centroids(db, get_llm_client()))
        invalidate_index()
