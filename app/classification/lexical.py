"""Stage 1 — lexical matcher.

An Aho–Corasick automaton over all active keywords (in folded form) finds every
keyword occurrence in one linear pass. Two rules make it correct for the tricky
Gujarati cases:

1. **Whole-token boundaries.** A match is valid only if it starts at a token
   start and ends at a token end. This stops ``ઉદ્યોગ`` from matching inside the
   single token ``મત્સ્યોદ્યોગ`` (trap T2).
2. **Longest match wins.** When two valid matches overlap, the one spanning more
   tokens is kept. So ``કુટિર ઉદ્યોગ`` (2 tokens → COTTAGE) beats the embedded
   ``ઉદ્યોગ`` (1 token → INDUSTRY) (trap T1).

Per-department score = ``sum(weight × token_count)`` over surviving matches,
then normalised so all department scores sum to 1.0. The automaton is cached and
rebuilt when keywords change.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.normalize import to_folded
from app.models import Department, Keyword


@dataclass
class Payload:
    term: str  # raw keyword term (for display)
    department_code: str
    weight: float
    token_count: int


@dataclass
class LexicalHit:
    term: str
    department_code: str
    start: int
    end: int
    weight: float
    token_count: int

    def as_dict(self) -> dict:
        return {
            "term": self.term,
            "department_code": self.department_code,
            "start": self.start,
            "end": self.end,
            "weight": self.weight,
            "token_count": self.token_count,
        }


@dataclass
class LexicalResult:
    scores: dict[str, float]        # normalised, sums to 1.0 (or all 0 if no hits)
    raw_scores: dict[str, float]    # sum(weight*token_count) per department
    hits: list[LexicalHit] = field(default_factory=list)
    total_hits: int = 0
    latency_ms: float = 0.0


class _AhoCorasick:
    """Character-level Aho–Corasick over a set of unique pattern strings."""

    def __init__(self, patterns: list[str]):
        self.patterns = patterns
        self.goto: list[dict[str, int]] = [{}]
        self.fail: list[int] = [0]
        self.out: list[list[int]] = [[]]
        for idx, word in enumerate(patterns):
            self._add(word, idx)
        self._build()

    def _add(self, word: str, idx: int) -> None:
        cur = 0
        for ch in word:
            nxt = self.goto[cur].get(ch)
            if nxt is None:
                nxt = len(self.goto)
                self.goto.append({})
                self.fail.append(0)
                self.out.append([])
                self.goto[cur][ch] = nxt
            cur = nxt
        self.out[cur].append(idx)

    def _build(self) -> None:
        q: deque[int] = deque()
        for _ch, s in self.goto[0].items():
            self.fail[s] = 0
            q.append(s)
        while q:
            r = q.popleft()
            for ch, s in self.goto[r].items():
                q.append(s)
                f = self.fail[r]
                while f and ch not in self.goto[f]:
                    f = self.fail[f]
                self.fail[s] = self.goto[f].get(ch, 0)
                if self.fail[s] == s:
                    self.fail[s] = 0
                self.out[s] = self.out[s] + self.out[self.fail[s]]

    def search(self, text: str):
        """Yield (start, end, pattern_index) for every occurrence."""
        cur = 0
        for i, ch in enumerate(text):
            while cur and ch not in self.goto[cur]:
                cur = self.fail[cur]
            cur = self.goto[cur].get(ch, 0)
            if self.out[cur]:
                for idx in self.out[cur]:
                    plen = len(self.patterns[idx])
                    yield (i - plen + 1, i + 1, idx)


class KeywordIndex:
    """A built automaton plus its payloads and the department universe."""

    def __init__(self, patterns: list[str], payloads: dict[int, list[Payload]], department_codes: list[str]):
        self._patterns = patterns
        self._payloads = payloads
        self.department_codes = department_codes
        self.automaton = _AhoCorasick(patterns) if patterns else None

    @staticmethod
    def _is_token_boundary_start(text: str, start: int) -> bool:
        return start == 0 or text[start - 1] == " "

    @staticmethod
    def _is_token_boundary_end(text: str, end: int) -> bool:
        return end == len(text) or text[end] == " "

    def match(self, folded_text: str) -> LexicalResult:
        started = time.perf_counter()
        raw_scores = {code: 0.0 for code in self.department_codes}
        if not self.automaton or not folded_text:
            return LexicalResult(scores=dict(raw_scores), raw_scores=raw_scores, hits=[], total_hits=0,
                                 latency_ms=(time.perf_counter() - started) * 1000)

        # Collect valid (token-boundary) candidate matches.
        candidates: list[tuple[int, int, Payload]] = []
        for start, end, idx in self.automaton.search(folded_text):
            if not self._is_token_boundary_start(folded_text, start):
                continue
            if not self._is_token_boundary_end(folded_text, end):
                continue
            for payload in self._payloads.get(idx, []):
                candidates.append((start, end, payload))

        # Longest-match-wins overlap resolution: prefer more tokens, then longer
        # char span, then earlier start. Keep a match only if its char range does
        # not overlap an already-kept range.
        candidates.sort(key=lambda c: (-c[2].token_count, -(c[1] - c[0]), c[0]))
        kept: list[tuple[int, int, Payload]] = []
        occupied: list[tuple[int, int]] = []
        for start, end, payload in candidates:
            if any(not (end <= o_start or start >= o_end) for o_start, o_end in occupied):
                continue
            kept.append((start, end, payload))
            occupied.append((start, end))

        hits: list[LexicalHit] = []
        for start, end, payload in sorted(kept, key=lambda c: c[0]):
            raw_scores[payload.department_code] += payload.weight * payload.token_count
            hits.append(
                LexicalHit(
                    term=payload.term,
                    department_code=payload.department_code,
                    start=start,
                    end=end,
                    weight=payload.weight,
                    token_count=payload.token_count,
                )
            )

        total = sum(raw_scores.values())
        if total > 0:
            scores = {code: value / total for code, value in raw_scores.items()}
        else:
            scores = {code: 0.0 for code in self.department_codes}

        return LexicalResult(
            scores=scores,
            raw_scores=raw_scores,
            hits=hits,
            total_hits=len(hits),
            latency_ms=(time.perf_counter() - started) * 1000,
        )


# ---- Module-level cache ------------------------------------------------------
_INDEX: KeywordIndex | None = None


def build_index(db: Session) -> KeywordIndex:
    """Build a fresh KeywordIndex from active keywords in the database."""
    department_codes = list(
        db.scalars(select(Department.code).where(Department.is_active.is_(True)).order_by(Department.code))
    )
    rows = db.execute(
        select(Keyword, Department.code)
        .join(Department, Keyword.department_id == Department.id)
        .where(Keyword.is_active.is_(True), Department.is_active.is_(True))
    ).all()

    pattern_to_index: dict[str, int] = {}
    patterns: list[str] = []
    payloads: dict[int, list[Payload]] = {}
    for keyword, dept_code in rows:
        folded = to_folded(keyword.term)
        if not folded:
            continue
        idx = pattern_to_index.get(folded)
        if idx is None:
            idx = len(patterns)
            pattern_to_index[folded] = idx
            patterns.append(folded)
            payloads[idx] = []
        payloads[idx].append(
            Payload(
                term=keyword.term,
                department_code=dept_code,
                weight=float(keyword.weight),
                token_count=int(keyword.token_count),
            )
        )
    return KeywordIndex(patterns, payloads, department_codes)


def get_index(db: Session) -> KeywordIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index(db)
    return _INDEX


def invalidate_index() -> None:
    """Drop the cached automaton so it is rebuilt on next use (keyword change)."""
    global _INDEX
    _INDEX = None


def match_text(db: Session, folded_text: str) -> LexicalResult:
    return get_index(db).match(folded_text)
