"""Tests for Stage 0 normalisation (app/classification/normalize.py)."""
from __future__ import annotations

from app.classification.normalize import (
    detect_language,
    fold,
    normalize,
    to_folded,
)


def test_nfc_and_whitespace_collapse():
    nt = normalize("  ગામમાં    વીજ   નથી  ")
    assert nt.normalized == "ગામમાં વીજ નથી"
    assert "  " not in nt.folded


def test_gujarati_digits_to_ascii():
    nt = normalize("વોર્ડ ૧૨૩ માં ૪૫ ફરિયાદ")
    assert "123" in nt.normalized
    assert "45" in nt.normalized


def test_variant_folding_matra_and_vowel():
    # લાઈટો and લાઇટ should share the stem after folding.
    assert fold("લાઈટો").startswith(fold("લાઇટ"))
    assert to_folded("ઈંટ") == to_folded("ઇંટ")
    # long U matra folds to short U matra
    assert fold("ભૂમિ") == fold("ભુમિ")


def test_zwj_zwnj_stripped():
    with_joiner = "ક\u200dષ"
    assert "\u200d" not in fold(with_joiner)


def test_stray_space_hyphen_normalisation():
    # The source keyword has a stray space after the hyphen.
    folded = to_folded("હાઈ- ટેન્શન લાઇન")
    assert "-" not in folded
    assert folded.split() == ["હાઇ", "ટેન્શન", "લાઇન"]


def test_intra_word_hyphen_preserved():
    folded = to_folded("લો-વોલ્ટેજ")
    assert "-" in folded
    assert folded.split() == ["લો-વોલ્ટેજ"]


def test_atm_dotted_form_folds_to_plain():
    assert to_folded("એ.ટી.એમ") == to_folded("એટીએમ")


def test_language_detection_gujarati():
    assert detect_language("ગામમાં વીજ નથી") == "gu"


def test_language_detection_english():
    assert detect_language("Primary school has no teacher") == "en"


def test_language_detection_gu_latn():
    nt = normalize("Amara gaam ma light nathi aavti")
    assert nt.language == "gu-latn"
    # Transliteration should expand at least the ENERGY term 'light'.
    assert any("લાઇટ" in fold(exp) or exp == "લાઇટ" for exp in nt.transliteration_expansions)


def test_transliteration_appended_to_folded():
    nt = normalize("gaam ma light nathi transformer bali gayu")
    assert "લાઇટ" in nt.folded or "ટ્રાન્સફોર્મર" in nt.folded
