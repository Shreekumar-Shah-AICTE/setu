"""Stage 4 — the LLM arbiter.

Invoked only when Stage 3 is uncertain (15–30% of traffic in practice). Builds a
prompt containing the grievance, the bilingual department list, the lexical
hits, the top-3 fused candidates and the trap disambiguation rules. Local models
are messy, so parsing is defensive: strip ``<think>`` blocks and markdown
fences, extract the first balanced ``{...}``, validate with Pydantic, and on
failure retry once with a repair prompt before falling back to the fused winner
(marking the trace degraded).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.llm.base import LLMClient, system_message, user_message
from app.llm.mock import (
    ARBITER_SENTINEL,
    FIELD_CANDIDATES,
    FIELD_GRIEVANCE,
    FIELD_LANGUAGE,
    FIELD_LEXICAL,
    VALID_CODES,
)

logger = logging.getLogger("setu.arbiter")

_VALID_URGENCY = {"CRITICAL", "HIGH", "NORMAL", "LOW"}

TRAP_RULES_TEXT = (
    "Disambiguation rules:\n"
    "- કુટિર ઉદ્યોગ (cottage industry) is COTTAGE, not INDUSTRY, even though it contains ઉદ્યોગ.\n"
    "- મત્સ્યોદ્યોગ is FISHERIES; do not match the ઉદ્યોગ substring to INDUSTRY.\n"
    "- ગેસ એજન્સી (LPG agency) is FOOD_CIVIL (civil supplies), not ENERGY.\n"
    "- Electricity/transformer/PGVCL/light/power belong to ENERGY.\n"
    "- MSP / ટેકાના ભાવ is primarily AGRICULTURE with FOOD_CIVIL as secondary.\n"
    "- Factory chimney smoke is INDUSTRY with ENVIRONMENT secondary.\n"
    "- Overloaded sand trucks are HOME (traffic) with MINES secondary.\n"
    "- Education, health, water supply, roads and revenue are not in the list -> OTHER."
)


class ArbiterOutput(BaseModel):
    department: str
    secondary_departments: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    urgency: str = "NORMAL"
    detected_language: str = "gu"
    reasoning_en: str = ""
    reasoning_gu: str = ""

    @field_validator("department")
    @classmethod
    def _valid_department(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in VALID_CODES:
            raise ValueError(f"department '{v}' is not one of {sorted(VALID_CODES)}")
        return v

    @field_validator("secondary_departments", mode="before")
    @classmethod
    def _clean_secondary(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip().upper() for x in v if str(x).strip().upper() in VALID_CODES]

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, f))

    @field_validator("urgency")
    @classmethod
    def _valid_urgency(cls, v: str) -> str:
        v = (v or "NORMAL").strip().upper()
        return v if v in _VALID_URGENCY else "NORMAL"


@dataclass
class ArbiterResult:
    parsed: Optional[ArbiterOutput]
    raw: str
    degraded: bool
    latency_ms: float
    model: str
    invoked: bool = True


def extract_json(text: str) -> str:
    """Strip <think> blocks and code fences, then return the first balanced {...}."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "")
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("unbalanced JSON object")


def parse_arbiter(content: str) -> ArbiterOutput:
    obj = json.loads(extract_json(content))
    return ArbiterOutput(**obj)


def build_prompt(
    *,
    grievance_text: str,
    language: str,
    departments: list[tuple[str, str, str]],  # (code, name_en, name_gu)
    lexical_hits: list[dict],
    candidates: list[tuple[str, float]],
) -> list[dict]:
    dept_lines = "\n".join(f"- {code}: {name_en} / {name_gu}" for code, name_en, name_gu in departments)
    cand_str = "; ".join(f"{code}={score:.3f}" for code, score in candidates[:3])
    if lexical_hits:
        lex_str = "; ".join(f"{h['term']}={h['department_code']}" for h in lexical_hits)
    else:
        lex_str = "none"
    one_line_grievance = " ".join(grievance_text.split())

    system = (
        "You are the routing arbiter for a Gujarat State Government grievance system. "
        "Classify the grievance into exactly one of the eleven departments and respond "
        "with a single JSON object only — no prose, no markdown. "
        f"{ARBITER_SENTINEL}"
    )
    schema = (
        '{"department": "CODE", "secondary_departments": ["CODE"], "confidence": 0.0, '
        '"urgency": "CRITICAL|HIGH|NORMAL|LOW", "detected_language": "gu|en|gu-latn|mixed", '
        '"reasoning_en": "...", "reasoning_gu": "..."}'
    )
    user = (
        f"{FIELD_GRIEVANCE} {one_line_grievance}\n"
        f"{FIELD_LANGUAGE} {language}\n"
        f"{FIELD_CANDIDATES} {cand_str}\n"
        f"{FIELD_LEXICAL} {lex_str}\n\n"
        f"Departments:\n{dept_lines}\n\n"
        f"{TRAP_RULES_TEXT}\n\n"
        f"Respond with JSON exactly matching this schema:\n{schema}"
    )
    return [system_message(system), user_message(user)]


def build_repair_prompt(previous: str, error: str) -> list[dict]:
    system = (
        "You returned output that failed JSON validation. Respond again with ONLY a valid "
        f"JSON object matching the required schema. {ARBITER_SENTINEL}"
    )
    user = (
        f"Previous output:\n{previous[:1500]}\n\n"
        f"Validation error: {error}\n\n"
        'Return only: {"department": "CODE", "secondary_departments": [], "confidence": 0.0, '
        '"urgency": "NORMAL", "detected_language": "gu", "reasoning_en": "", "reasoning_gu": ""}'
    )
    return [system_message(system), user_message(user)]


async def run_arbiter(
    client: LLMClient,
    *,
    grievance_text: str,
    language: str,
    departments: list[tuple[str, str, str]],
    lexical_hits: list[dict],
    candidates: list[tuple[str, float]],
    model: str | None = None,
) -> ArbiterResult:
    model = model or get_settings().arbiter_model
    started = time.perf_counter()
    messages = build_prompt(
        grievance_text=grievance_text, language=language, departments=departments,
        lexical_hits=lexical_hits, candidates=candidates,
    )
    result = await client.chat(model=model, messages=messages, temperature=0.0, json_mode=True)
    raw = result.content
    degraded = bool(result.degraded)

    try:
        parsed = parse_arbiter(raw)
        return ArbiterResult(parsed, raw, degraded, (time.perf_counter() - started) * 1000, model)
    except Exception as first_error:  # noqa: BLE001 - messy model output is expected
        logger.warning("Arbiter output failed validation (%s); retrying with repair prompt", first_error)
        repair = build_repair_prompt(raw, str(first_error))
        result2 = await client.chat(model=model, messages=repair, temperature=0.0, json_mode=True)
        combined_raw = f"{raw}\n---REPAIR---\n{result2.content}"
        degraded = degraded or bool(result2.degraded)
        try:
            parsed = parse_arbiter(result2.content)
            return ArbiterResult(parsed, combined_raw, degraded, (time.perf_counter() - started) * 1000, model)
        except Exception as second_error:  # noqa: BLE001
            logger.warning("Arbiter repair also failed (%s); falling back to fused winner", second_error)
            return ArbiterResult(
                None, combined_raw, True, (time.perf_counter() - started) * 1000, model
            )
