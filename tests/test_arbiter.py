"""Tests for Stage 4 arbiter parsing and robustness."""
from __future__ import annotations

from app.classification.arbiter import (
    ArbiterOutput,
    extract_json,
    parse_arbiter,
    run_arbiter,
)
from app.llm.base import ChatResult

VALID_JSON = (
    '{"department": "ENERGY", "secondary_departments": ["ENVIRONMENT"], '
    '"confidence": 0.94, "urgency": "HIGH", "detected_language": "gu", '
    '"reasoning_en": "burnt transformer", "reasoning_gu": "ટ્રાન્સફોર્મર"}'
)


def test_extract_json_strips_think_block():
    raw = "<think>the user says...</think>\n" + VALID_JSON
    assert extract_json(raw).startswith("{")
    out = parse_arbiter(raw)
    assert out.department == "ENERGY"


def test_extract_json_strips_code_fences():
    raw = "```json\n" + VALID_JSON + "\n```"
    out = parse_arbiter(raw)
    assert out.department == "ENERGY"
    assert out.secondary_departments == ["ENVIRONMENT"]


def test_extract_first_balanced_object_with_trailing_text():
    raw = "Here you go: " + VALID_JSON + " -- hope that helps!"
    out = parse_arbiter(raw)
    assert out.confidence == 0.94


def test_invalid_department_rejected():
    import pytest

    with pytest.raises(Exception):
        ArbiterOutput(department="TRANSPORT", confidence=0.5)


def test_confidence_clamped_and_urgency_defaulted():
    out = ArbiterOutput(department="home", confidence=5.0, urgency="banana")
    assert out.department == "HOME"
    assert out.confidence == 1.0
    assert out.urgency == "NORMAL"


class _ScriptedClient:
    """A fake LLM client returning programmed chat contents in sequence."""

    def __init__(self, contents: list[str], degraded: bool = False):
        self._contents = contents
        self._i = 0
        self.degraded = degraded

    @property
    def name(self):
        return "scripted"

    async def chat(self, *, model, messages, temperature=0.0, max_tokens=1024, json_mode=False):
        content = self._contents[min(self._i, len(self._contents) - 1)]
        self._i += 1
        return ChatResult(content=content, model=model, provider="scripted", degraded=self.degraded)

    async def embed(self, *, model, texts):
        return [[0.0]] * len(texts)

    async def rerank(self, *, model, query, documents, top_n=5, instruction=None):
        return []

    async def health(self):
        from app.llm.base import ProviderHealth

        return ProviderHealth(provider="scripted", healthy=True)


DEPTS = [("ENERGY", "Energy", "ઊર્જા"), ("ENVIRONMENT", "Environment", "પર્યાવરણ")]


async def test_run_arbiter_happy_path():
    client = _ScriptedClient([VALID_JSON])
    res = await run_arbiter(
        client, grievance_text="ટ્રાન્સફોર્મર", language="gu", departments=DEPTS,
        lexical_hits=[], candidates=[("ENERGY", 0.4), ("ENVIRONMENT", 0.3)],
    )
    assert res.parsed is not None
    assert res.parsed.department == "ENERGY"
    assert res.degraded is False


async def test_run_arbiter_retry_then_success():
    client = _ScriptedClient(["not json at all", VALID_JSON])
    res = await run_arbiter(
        client, grievance_text="x", language="gu", departments=DEPTS,
        lexical_hits=[], candidates=[("ENERGY", 0.4)],
    )
    assert res.parsed is not None
    assert res.parsed.department == "ENERGY"


async def test_run_arbiter_double_failure_falls_back():
    client = _ScriptedClient(["garbage", "still garbage"])
    res = await run_arbiter(
        client, grievance_text="x", language="gu", departments=DEPTS,
        lexical_hits=[], candidates=[("ENERGY", 0.4)],
    )
    assert res.parsed is None
    assert res.degraded is True
