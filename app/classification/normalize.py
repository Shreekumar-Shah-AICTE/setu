"""Stage 0 — text normalisation.

A pure function (no I/O beyond a one-time YAML load of the transliteration
lexicon). Given raw grievance text it produces a :class:`NormalizedText` with:

* ``raw``            — the original text, untouched
* ``normalized``     — NFC + whitespace-collapsed + digits + punctuation-stripped
* ``folded``         — the canonical comparison form used for lexical matching
* ``tokens``         — whitespace tokens of ``folded``
* ``language``       — one of ``gu`` | ``en`` | ``gu-latn`` | ``mixed``
* ``transliteration_expansions`` — Gujarati expansions appended for gu-latn text

Variant folding maps ``ઈ→ઇ``, ``ઊ→ઉ``, matra ``ી→િ`` and ``ૂ→ુ`` and strips
ZWJ/ZWNJ, so ``લાઈટો`` and ``લાઇટ`` share a stem. The original text is never
mutated — folding exists only to make matching robust.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings

# Gujarati Unicode block.
_GU_START, _GU_END = 0x0A80, 0x0AFF

# Gujarati digits ૦-૯ -> ASCII 0-9.
_GU_DIGITS = {ord("૦") + i: str(i) for i in range(10)}

# Variant folding: fold long vowels/matras into short, strip joiners.
_FOLD_MAP = {
    "ઈ": "ઇ",   # long I vowel -> short I
    "ઊ": "ઉ",   # long U vowel -> short U
    "ી": "િ",   # long I matra -> short I matra
    "ૂ": "ુ",   # long U matra -> short U matra
    "\u200d": "",  # ZWJ
    "\u200c": "",  # ZWNJ
}
_FOLD_TRANS = {ord(k): (v if v else None) for k, v in _FOLD_MAP.items()}

# Romanised-Gujarati marker words. Presence of any of these in Latin-dominant
# text signals "Gujlish" (gu-latn) rather than English.
ROMAN_MARKERS: set[str] = {
    "nathi", "chhe", "che", "aavti", "aave", "thay", "thai", "karva", "mane",
    "amara", "amari", "aapno", "gaam", "gam", "paani", "pani", "light", "vij",
    "vijli", "ration", "khedut", "khedu", "majoori", "majuri", "arji", "farriyad",
    "fariyad", "saheb", "saheb", "taluka", "gamda", "nagarpalika", "sarpanch",
    "ma", "che", "thayu", "gayu", "bali", "nagar", "sarkar", "adhikari",
}

# A small English common-word list used to distinguish plain English from
# romanised Gujarati when Latin script dominates.
ENGLISH_WORDS: set[str] = {
    "the", "is", "are", "no", "not", "has", "have", "please", "complaint",
    "water", "road", "school", "teacher", "hospital", "village", "power",
    "electricity", "supply", "office", "officer", "department", "government",
    "problem", "issue", "request", "action", "days", "month", "since", "been",
    "there", "here", "our", "we", "they", "primary", "and", "for", "with",
    "of", "in", "at", "on", "to", "from", "this", "that", "your", "my",
}


@dataclass
class NormalizedText:
    raw: str
    normalized: str
    folded: str
    tokens: list[str] = field(default_factory=list)
    language: str = "mixed"
    transliteration_expansions: list[str] = field(default_factory=list)


def _clean(raw: str) -> str:
    """NFC, Gujarati digits -> ASCII, whitespace collapse + trim."""
    text = unicodedata.normalize("NFC", raw or "")
    text = text.translate(_GU_DIGITS)
    text = " ".join(text.split())
    return text


def _strip_punct(text: str) -> str:
    """Remove punctuation, keeping only intra-word hyphens."""
    out_chars: list[str] = []
    for ch in text:
        if ch == "-":
            out_chars.append(ch)
        elif ch.isspace():
            out_chars.append(ch)
        elif unicodedata.category(ch).startswith("P"):
            continue  # drop the punctuation character
        else:
            out_chars.append(ch)
    text = "".join(out_chars)
    # Drop hyphens that are not between two non-space characters
    # (handles the stray space in "હાઈ- ટેન્શન લાઇન").
    text = re.sub(r"(?<!\S)-|-(?!\S)", "", text)
    text = " ".join(text.split())
    return text


def fold(text: str) -> str:
    """Apply variant folding and lowercase ASCII (safe to call on any string).

    Lowercasing makes Latin matching case-insensitive so ``GIDC`` and ``gidc``
    fold to the same form; Gujarati script is unaffected by ``lower()``.
    """
    return text.translate(_FOLD_TRANS).lower()


def to_folded(raw: str) -> str:
    """Full pipeline to the matching form, without language/transliteration.

    Used to fold seed keywords identically to grievance text.
    """
    return fold(_strip_punct(_clean(raw)))


@lru_cache(maxsize=1)
def _translit_table() -> tuple[dict[str, str], dict[str, str]]:
    """Load romanised->Gujarati mappings. Returns (single-token, multi-token)."""
    path = Path(get_settings().data_dir) / "translit.yaml"
    singles: dict[str, str] = {}
    multi: dict[str, str] = {}
    if path.exists():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, value in (doc.get("mappings") or {}).items():
            k = str(key).strip().lower()
            if " " in k:
                multi[k] = str(value)
            else:
                singles[k] = str(value)
    return singles, multi


def reload_translit_table() -> None:
    _translit_table.cache_clear()


def detect_language(normalized: str) -> str:
    guj = sum(1 for ch in normalized if _GU_START <= ord(ch) <= _GU_END)
    latin = sum(1 for ch in normalized if ("a" <= ch.lower() <= "z"))
    total = guj + latin
    if total == 0:
        return "en"
    guj_ratio = guj / total
    if guj_ratio >= 0.5:
        return "gu"
    latin_ratio = latin / total
    if latin_ratio >= 0.6:
        tokens = {t.lower() for t in normalized.split()}
        if tokens & ROMAN_MARKERS:
            return "gu-latn"
        if tokens & ENGLISH_WORDS:
            return "en"
        return "mixed"
    return "mixed"


def expand_transliteration(tokens: list[str]) -> list[str]:
    """Return Gujarati expansions for romanised tokens (single + bigram)."""
    singles, multi = _translit_table()
    expansions: list[str] = []
    lowered = [t.lower() for t in tokens]
    # Bigrams first (e.g. "manav kalyan").
    for i in range(len(lowered) - 1):
        bigram = f"{lowered[i]} {lowered[i + 1]}"
        if bigram in multi:
            expansions.append(multi[bigram])
    for tok in lowered:
        if tok in singles:
            expansions.append(singles[tok])
    return expansions


def normalize(raw: str) -> NormalizedText:
    clean = _clean(raw)
    normalized = _strip_punct(clean)
    folded = fold(normalized)
    tokens = folded.split()
    language = detect_language(normalized)

    expansions: list[str] = []
    if language == "gu-latn":
        expansions = expand_transliteration(normalized.split())
        if expansions:
            folded_expansions = " ".join(fold(e) for e in expansions)
            folded = f"{folded} {folded_expansions}".strip()
            normalized = f"{normalized} {' '.join(expansions)}".strip()
            tokens = folded.split()

    return NormalizedText(
        raw=raw,
        normalized=normalized,
        folded=folded,
        tokens=tokens,
        language=language,
        transliteration_expansions=expansions,
    )
