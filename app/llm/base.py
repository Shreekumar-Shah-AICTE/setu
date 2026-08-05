"""The provider-agnostic LLM interface.

Every provider (mock, gateway, local) implements :class:`LLMClient`. The rest of
the system depends only on this Protocol, so switching providers is a one-line
change in configuration — the architectural centrepiece of SETU.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class ChatResult:
    content: str
    model: str
    provider: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    degraded: bool = False
    raw: Optional[dict] = None


@dataclass
class RerankHit:
    index: int
    score: float
    document: Optional[str] = None


@dataclass
class ProviderHealth:
    provider: str
    healthy: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)
    degraded: bool = False


def system_message(content: str) -> dict:
    return {"role": "system", "content": content}


def user_message(content: str) -> dict:
    return {"role": "user", "content": content}


@runtime_checkable
class LLMClient(Protocol):
    """The contract shared by all providers."""

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult: ...

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...

    async def rerank(
        self,
        *,
        model: str,
        query: str,
        documents: list[str],
        top_n: int = 5,
        instruction: Optional[str] = None,
    ) -> list[RerankHit]: ...

    async def health(self) -> ProviderHealth: ...

    @property
    def name(self) -> str: ...
