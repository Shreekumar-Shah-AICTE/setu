"""Pydantic schemas for the JSON API and bilingual form validation."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from app.reference import DISTRICT_VALUES

_PHONE_RE = re.compile(r"^(?:\+91[-\s]?)?[6-9]\d{9}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---- Bilingual form validation ----------------------------------------------
def validate_submission(data: dict) -> dict[str, tuple[str, str]]:
    """Return {field: (english_error, gujarati_error)} — empty if valid."""
    errors: dict[str, tuple[str, str]] = {}
    name = (data.get("citizen_name") or "").strip()
    phone = (data.get("citizen_phone") or "").strip()
    email = (data.get("citizen_email") or "").strip()
    district = (data.get("citizen_district") or "").strip()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()

    if len(name) < 2:
        errors["citizen_name"] = ("Please enter your name.", "કૃપા કરી તમારું નામ દાખલ કરો.")
    if not _PHONE_RE.match(phone.replace(" ", "").replace("-", "")):
        errors["citizen_phone"] = ("Enter a valid 10-digit mobile number.", "માન્ય ૧૦-અંકનો મોબાઈલ નંબર દાખલ કરો.")
    if email and not _EMAIL_RE.match(email):
        errors["citizen_email"] = ("Enter a valid email or leave it blank.", "માન્ય ઈમેલ દાખલ કરો અથવા ખાલી રાખો.")
    if district not in DISTRICT_VALUES:
        errors["citizen_district"] = ("Please select your district.", "કૃપા કરી તમારો જિલ્લો પસંદ કરો.")
    if len(subject) < 3:
        errors["subject"] = ("Please enter a subject.", "કૃપા કરી વિષય દાખલ કરો.")
    if len(body) < 10:
        errors["body"] = ("Please describe your grievance (at least 10 characters).",
                          "કૃપા કરી તમારી ફરિયાદ વર્ણવો (ઓછામાં ઓછા ૧૦ અક્ષર).")
    return errors


# ---- JSON API models ---------------------------------------------------------
class GrievanceCreate(BaseModel):
    citizen_name: str = Field(min_length=2, max_length=128)
    citizen_phone: str
    citizen_email: Optional[str] = None
    citizen_district: Optional[str] = None
    subject: str = Field(min_length=3, max_length=256)
    body: str = Field(min_length=10)


class ClassifyRequest(BaseModel):
    subject: str = ""
    body: str = Field(min_length=1)


class DepartmentOut(BaseModel):
    code: str
    name_en: str
    name_gu: str


class GrievanceOut(BaseModel):
    ref_no: str
    status: str
    department: Optional[str] = None
    urgency: str
    confidence: Optional[float] = None
    current_level: Optional[str] = None
    created_at: Optional[str] = None
    sla_due_at: Optional[str] = None
