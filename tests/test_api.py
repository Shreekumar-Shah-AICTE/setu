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
