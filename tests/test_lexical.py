"""Tests for Stage 1 lexical matching (app/classification/lexical.py)."""
from __future__ import annotations

from app.classification.lexical import build_index, match_text
from app.classification.normalize import normalize


def _match(db, text):
    nt = normalize(text)
    return nt, match_text(db, nt.folded)


def test_scores_normalised_to_one(db):
    _nt, res = _match(db, "ગામમાં વીજ નથી અને ટ્રાન્સફોર્મર બળી ગયું")
    assert res.total_hits > 0
    assert abs(sum(res.scores.values()) - 1.0) < 1e-9


def test_no_hits_gives_zero_scores(db):
    _nt, res = _match(db, "xyzzy qwerty foobar")
    assert res.total_hits == 0
    assert sum(res.scores.values()) == 0.0


def test_token_boundary_prevents_substring_match(db):
    # ઉદ્યોગ must NOT match inside the single token મત્સ્યોદ્યોગ.
    _nt, res = _match(db, "મત્સ્યોદ્યોગ")
    hit_terms = {h.term for h in res.hits}
    assert "ઉદ્યોગ" not in hit_terms
    assert res.hits and res.hits[0].department_code == "FISHERIES"


def test_longest_match_wins(db):
    # કુટિર ઉદ્યોગ (2 tokens, COTTAGE) beats embedded ઉદ્યોગ (1 token, INDUSTRY).
    _nt, res = _match(db, "કુટિર ઉદ્યોગ ને સહાય")
    kept_terms = {(h.term, h.department_code) for h in res.hits}
    assert ("કુટિર ઉદ્યોગ", "COTTAGE") in kept_terms
    assert ("ઉદ્યોગ", "INDUSTRY") not in kept_terms


def test_hits_have_character_offsets(db):
    nt, res = _match(db, "વીજ સમસ્યા")
    for h in res.hits:
        assert 0 <= h.start < h.end <= len(nt.folded)
        assert nt.folded[h.start:h.end]  # non-empty slice


def test_lexical_latency_under_5ms(db):
    # Build once, then time only the match on a realistic paragraph.
    index = build_index(db)
    nt = normalize(
        "અમારા ગામમાં છેલ્લા પાંચ દિવસથી ટ્રાન્સફોર્મર બળી ગયું છે અને અંધારપટ છે. "
        "પીજીવીસીએલને ફરિયાદ કરી પણ કોઈ જવાબ મળ્યો નથી. વીજપોલ પણ તૂટેલો છે."
    )
    # Warm run then measured run.
    index.match(nt.folded)
    res = index.match(nt.folded)
    assert res.latency_ms < 5.0, f"lexical match took {res.latency_ms:.3f} ms"
