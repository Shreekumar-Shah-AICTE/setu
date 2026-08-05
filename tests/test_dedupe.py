"""Tests for duplicate detection."""
from __future__ import annotations

from app.classification.pipeline import intake_grievance
from app.vectors import rebuild

DUP_TEXT = "અમારા ગામમાં ટ્રાન્સફોર્મર બળી ગયું છે અને છેલ્લા પાંચ દિવસથી અંધારપટ છે પીજીવીસીએલ"


async def test_identical_grievance_same_district_is_duplicate(db):
    rebuild(db)
    g1, _ = await intake_grievance(
        db, citizen_name="A", subject="વીજ", body=DUP_TEXT, citizen_district="Surat"
    )
    assert g1.status != "DUPLICATE"
    g2, _ = await intake_grievance(
        db, citizen_name="B", subject="વીજ", body=DUP_TEXT, citizen_district="Surat"
    )
    assert g2.status == "DUPLICATE"
    assert g2.duplicate_of_id == g1.id


async def test_same_text_different_district_is_not_duplicate(db):
    rebuild(db)
    g1, _ = await intake_grievance(
        db, citizen_name="A", subject="વીજ", body=DUP_TEXT, citizen_district="Rajkot"
    )
    g2, _ = await intake_grievance(
        db, citizen_name="B", subject="વીજ", body=DUP_TEXT, citizen_district="Kutch"
    )
    assert g2.status != "DUPLICATE"


async def test_dissimilar_grievance_is_not_duplicate(db):
    rebuild(db)
    await intake_grievance(
        db, citizen_name="A", subject="વીજ", body=DUP_TEXT, citizen_district="Anand"
    )
    g2, _ = await intake_grievance(
        db, citizen_name="B", subject="રાશન",
        body="રાશન કાર્ડ પર અનાજ મળતું નથી પ્રાઈસ શોપ વાળા કહે છે પુરવઠો આવ્યો નથી",
        citizen_district="Anand",
    )
    assert g2.status != "DUPLICATE"
