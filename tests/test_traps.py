"""The twelve classification traps (T1–T12).

These are the most important tests in the repository. At the lexical stage we
assert the *primary* department (and, for genuinely cross-departmental cases,
that both candidate departments are detected). Full-pipeline handling of
secondaries and the OTHER fallback is additionally verified in
``test_pipeline.py`` once the semantic + arbiter stages exist.
"""
from __future__ import annotations

from app.classification.lexical import match_text
from app.classification.normalize import normalize


def _classify(db, text):
    nt = normalize(text)
    res = match_text(db, nt.folded)
    top = max(res.scores, key=res.scores.get) if res.total_hits else None
    hit_depts = {h.department_code for h in res.hits}
    return nt, res, top, hit_depts


def test_T1_kutir_udyog_is_cottage(db):
    _nt, _res, top, _ = _classify(db, "કુટિર ઉદ્યોગ માટે માનવ કલ્યાણ યોજના હેઠળ ટુલકીટ મળી નથી")
    assert top == "COTTAGE"


def test_T2_matsyodyog_is_fisheries_not_industry(db):
    _nt, _res, top, hit_depts = _classify(db, "મત્સ્યોદ્યોગ વિભાગમાં મારી અરજી પેન્ડિંગ છે")
    assert top == "FISHERIES"
    assert "INDUSTRY" not in hit_depts


def test_T3_gas_agency_is_food_civil(db):
    _nt, _res, top, _ = _classify(db, "ગેસ એજન્સી બે મહિનાથી સિલિન્ડર આપતી નથી")
    assert top == "FOOD_CIVIL"


def test_T4_light_matra_variants_are_energy(db):
    for text in ("ગામમાં લાઈટો બંધ છે", "ઘરમાં લાઇટ નથી આવતી"):
        _nt, _res, top, _ = _classify(db, text)
        assert top == "ENERGY", text


def test_T5_nana_panch_space_variants_are_finance(db):
    for text in ("નાણા પંચ ની ભલામણ", "નાણાપંચ ની ભલામણ"):
        _nt, _res, top, _ = _classify(db, text)
        assert top == "FINANCE", text


def test_T6_high_tension_line_is_energy(db):
    _nt, _res, top, _ = _classify(db, "ગામમાં હાઈ- ટેન્શન લાઇન નીચેથી પસાર થાય છે")
    assert top == "ENERGY"


def test_T7_msp_is_agriculture_primary(db):
    # Genuinely cross-departmental (AGRICULTURE + FOOD_CIVIL); lexical picks AGRICULTURE.
    _nt, _res, top, _ = _classify(db, "ટેકાના ભાવ થી ખરીદી શરૂ થઈ નથી")
    assert top == "AGRICULTURE"


def test_T8_factory_chimney_smoke_is_industry_and_environment(db):
    _nt, _res, top, hit_depts = _classify(
        db, "જીઆઇડીસી કારખાના ચીમની માંથી કાળો ધૂમાડો અને પર્યાવરણ ને નુકસાન"
    )
    assert "INDUSTRY" in hit_depts and "ENVIRONMENT" in hit_depts
    assert top == "INDUSTRY"


def test_T9_overloaded_sand_truck_is_home_and_mines(db):
    _nt, _res, _top, hit_depts = _classify(db, "ઓવરલોડિંગ વાહન રેતી ખનન ટ્રક રાત્રે ભરે છે")
    assert "HOME" in hit_depts and "MINES" in hit_depts


def test_T10_english_school_has_no_lexical_hits(db):
    # No seeded keyword matches -> zero hits -> the fusion stage assigns OTHER.
    _nt, res, top, _ = _classify(db, "Primary school has no teacher in the village since last year")
    assert res.total_hits == 0
    assert top is None


def test_T11_romanised_gujlish_is_energy(db):
    _nt, _res, top, _ = _classify(
        db, "Amara gaam ma light nathi aavti, transformer bali gayu chhe, PGVCL ne kai vaar kahyu"
    )
    assert top == "ENERGY"


def test_T12_power_loanword_is_energy(db):
    _nt, _res, top, _ = _classify(db, "ગામમાં પાવર સપ્લાય ની સમસ્યા છે")
    assert top == "ENERGY"
