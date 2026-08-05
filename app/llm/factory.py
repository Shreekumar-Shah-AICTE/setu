"""Provider factory — the single switch selected by ``LLM_PROVIDER``.

``mock`` (default) | ``gateway`` | ``local``. The chosen client is cached; tests
and the admin console can reset it after changing configuration.
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.llm.base import LLMClient

logger = logging.getLogger("setu.llm")

_CLIENT: LLMClient | None = None
_CLIENT_PROVIDER: str | None = None


def _build(provider: str) -> LLMClient:
    provider = (provider or "mock").lower()
    if provider == "gateway":
        from app.llm.gateway import OllamaGatewayClient

        logger.info("LLM provider = gateway")
        return OllamaGatewayClient()
    if provider == "local":
        from app.llm.local import LocalEmbeddingClient

        logger.info("LLM provider = local")
        return LocalEmbeddingClient()
    from app.llm.mock import MockLLMClient

    logger.info("LLM provider = mock")
    return MockLLMClient()


def get_llm_client() -> LLMClient:
    global _CLIENT, _CLIENT_PROVIDER
    provider = get_settings().llm_provider
    if _CLIENT is None or _CLIENT_PROVIDER != provider:
        _CLIENT = _build(provider)
        _CLIENT_PROVIDER = provider
    return _CLIENT


def reset_llm_client() -> None:
    """Drop the cached client (used by tests and when settings change)."""
    global _CLIENT, _CLIENT_PROVIDER
    _CLIENT = None
    _CLIENT_PROVIDER = None
