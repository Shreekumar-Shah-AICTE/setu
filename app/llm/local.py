"""LocalEmbeddingClient — optional real multilingual embeddings.

Produces genuine sentence embeddings via ``sentence-transformers`` and delegates
``chat`` / ``rerank`` to the mock provider. The import is lazy and guarded: if
the package or the model weights are missing, it logs one warning and falls back
to mock embeddings so the application still starts and the tests still pass on a
machine that has never heard of PyTorch. The embedding dimensionality is read
from the model at load time, never assumed.

This provider exists for *measurement* (the Phase-12 ablation), not deployment.
``LLM_PROVIDER=mock`` remains the default.
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.llm.base import ChatResult, ProviderHealth, RerankHit
from app.llm.mock import MockLLMClient

logger = logging.getLogger("setu.local")


class LocalEmbeddingClient:
    def __init__(self) -> None:
        self._name = "local"
        self._mock = MockLLMClient()
        self._model = None
        self._available: bool | None = None
        self._dim: int | None = None
        self._warned = False

    @property
    def name(self) -> str:
        return self._name

    def _ensure_model(self) -> bool:
        if self._available is not None:
            return self._available
        model_name = get_settings().local_embedding_model
        try:
            from sentence_transformers import SentenceTransformer  # lazy, optional

            self._model = SentenceTransformer(model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
            self._available = True
            logger.info("Loaded local embedding model %s (%d dims)", model_name, self._dim)
        except Exception as exc:  # ImportError or model download/load failure
            self._available = False
            if not self._warned:
                logger.warning(
                    "Local embedding model unavailable (%s); falling back to mock embeddings. "
                    "Install requirements-local.txt to enable real embeddings.", exc,
                )
                self._warned = True
        return self._available

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        if self._ensure_model():
            vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return [v.tolist() for v in vectors]
        return await self._mock.embed(model=model, texts=texts)

    async def chat(self, *, model, messages, temperature=0.0, max_tokens=1024, json_mode=False) -> ChatResult:
        return await self._mock.chat(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, json_mode=json_mode,
        )

    async def rerank(self, *, model, query, documents, top_n=5, instruction=None) -> list[RerankHit]:
        return await self._mock.rerank(
            model=model, query=query, documents=documents, top_n=top_n, instruction=instruction
        )

    async def health(self) -> ProviderHealth:
        available = self._ensure_model()
        if available:
            return ProviderHealth(
                provider="local", healthy=True,
                detail=f"sentence-transformers model loaded ({self._dim} dims)",
                models=[get_settings().local_embedding_model],
            )
        return ProviderHealth(
            provider="local", healthy=True, degraded=True,
            detail="sentence-transformers unavailable; using mock embeddings",
        )

    @property
    def embedding_dim(self) -> int | None:
        return self._dim
