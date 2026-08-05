"""OllamaGatewayClient — the real BeyonData integration.

Targets an OpenAI-compatible Ollama gateway using only ``/v1/`` endpoints. It is
written defensively because it cannot be tested against the real gateway during
development: configurable auth, retries with exponential backoff + jitter, a
circuit breaker, and — when ``LLM_FALLBACK_TO_MOCK`` is set — transparent
fallback to the mock provider so the demo never crashes when the gateway is
down.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from app.config import get_settings
from app.llm.base import ChatResult, ProviderHealth, RerankHit
from app.llm.mock import MockLLMClient

logger = logging.getLogger("setu.gateway")

RETRY_STATUS = {429, 500, 502, 503, 504}

# Always pass this explicit instruction to /v1/rerank. The gateway ships a
# DEFAULT instruction written for a different internal project (tender/bidder
# matching) — never rely on it.
DOMAIN_RERANK_INSTRUCTION = (
    "Given a citizen grievance, rank the candidate government department "
    "descriptions by how well each department is responsible for resolving it."
)


class GatewayError(Exception):
    """Raised when the gateway is unreachable or returns an error."""


class CircuitBreaker:
    def __init__(self, threshold: int, reset_seconds: float):
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self.opened_until

    def record_success(self) -> None:
        self.failures = 0
        self.opened_until = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_until = time.monotonic() + self.reset_seconds


class OllamaGatewayClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        fallback_client: MockLLMClient | None = None,
        backoff_base: float = 0.5,
    ) -> None:
        s = get_settings()
        self._name = "gateway"
        self.base_url = s.ollama_gateway_base_url.rstrip("/")
        self.auth_scheme = (s.ollama_gateway_auth_scheme or "bearer").lower()
        self.auth_header = s.ollama_gateway_auth_header or "Authorization"
        self.api_key = s.ollama_gateway_api_key or ""
        self.max_retries = s.ollama_gateway_max_retries
        self.fallback_enabled = s.llm_fallback_to_mock
        self.backoff_base = backoff_base
        self.degraded = False

        self.breaker = CircuitBreaker(
            s.ollama_gateway_circuit_fail_threshold, s.ollama_gateway_circuit_reset_seconds
        )
        self._external_client = http_client is not None
        self.client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=s.ollama_gateway_connect_timeout,
                read=s.ollama_gateway_read_timeout,
                write=s.ollama_gateway_read_timeout,
                pool=s.ollama_gateway_connect_timeout,
            )
        )
        self._fallback = fallback_client or MockLLMClient()

    @property
    def name(self) -> str:
        return self._name

    async def aclose(self) -> None:
        if not self._external_client:
            await self.client.aclose()

    # ---- Auth ----
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_scheme == "bearer" and self.api_key:
            headers[self.auth_header] = f"Bearer {self.api_key}"
        elif self.auth_scheme == "header" and self.api_key:
            headers[self.auth_header] = self.api_key
        return headers

    def _params(self) -> dict:
        if self.auth_scheme == "query" and self.api_key:
            key_name = self.auth_header if self.auth_header.lower() != "authorization" else "api_key"
            return {key_name: self.api_key}
        return {}

    # ---- Core request with retries + circuit breaker ----
    async def _request(self, method: str, path: str, json_body: dict | None = None) -> httpx.Response:
        if self.breaker.is_open():
            raise GatewayError("circuit breaker is open")

        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self.client.request(
                    method, url, json=json_body, headers=self._headers(), params=self._params()
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                self.breaker.record_failure()
                if attempt < self.max_retries:
                    await self._sleep_backoff(attempt)
                    continue
                raise GatewayError(f"connection error: {exc}") from exc

            if resp.status_code in RETRY_STATUS:
                last_error = GatewayError(f"retryable status {resp.status_code}")
                self.breaker.record_failure()
                if attempt < self.max_retries:
                    await self._sleep_backoff(attempt)
                    continue
                raise last_error
            if resp.status_code >= 400:
                # Non-retryable client error (e.g. 404 for a missing endpoint).
                raise GatewayError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            self.breaker.record_success()
            return resp

        raise GatewayError(str(last_error) if last_error else "request failed")

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = self.backoff_base * (2 ** attempt) + random.uniform(0, self.backoff_base / 2)
        await asyncio.sleep(delay)

    def _log_call(self, endpoint: str, model: str, latency_ms: float, outcome: str, extra: str = "") -> None:
        logger.info("gateway call endpoint=%s model=%s latency=%.0fms outcome=%s %s",
                    endpoint, model, latency_ms, outcome, extra)

    # ---- Public interface --------------------------------------------------
    async def chat(
        self, *, model: str, messages: list[dict], temperature: float = 0.0,
        max_tokens: int = 1024, json_mode: bool = False,
    ) -> ChatResult:
        body: dict = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            resp = await self._request("POST", "/v1/chat/completions", body)
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {}) or {}
            latency = (time.perf_counter() - started) * 1000
            self._log_call("/v1/chat/completions", model, latency, "ok")
            return ChatResult(
                content=content, model=model, provider="gateway",
                prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                latency_ms=latency, degraded=False, raw=data,
            )
        except GatewayError as exc:
            latency = (time.perf_counter() - started) * 1000
            self._log_call("/v1/chat/completions", model, latency, "error", str(exc))
            if not self.fallback_enabled:
                raise
            self.degraded = True
            result = await self._fallback.chat(
                model=model, messages=messages, temperature=temperature,
                max_tokens=max_tokens, json_mode=json_mode,
            )
            result.provider = "mock(fallback)"
            result.degraded = True
            return result

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        try:
            resp = await self._request("POST", "/v1/embeddings", {"model": model, "input": texts})
            data = resp.json()
            embeddings = [row["embedding"] for row in data["data"]]
            self._log_call("/v1/embeddings", model, (time.perf_counter() - started) * 1000, "ok",
                           f"n={len(texts)}")
            return embeddings
        except GatewayError as exc:
            self._log_call("/v1/embeddings", model, (time.perf_counter() - started) * 1000, "error", str(exc))
            if not self.fallback_enabled:
                raise
            self.degraded = True
            return await self._fallback.embed(model=model, texts=texts)

    async def rerank(
        self, *, model: str, query: str, documents: list[str], top_n: int = 5,
        instruction: str | None = None,
    ) -> list[RerankHit]:
        body = {
            "model": model, "query": query, "documents": documents, "top_n": top_n,
            "return_documents": True, "instruction": instruction or DOMAIN_RERANK_INSTRUCTION,
        }
        started = time.perf_counter()
        try:
            resp = await self._request("POST", "/v1/rerank", body)
            data = resp.json()
            results = data.get("results", data.get("data", []))
            hits: list[RerankHit] = []
            for item in results:
                idx = item.get("index")
                score = item.get("relevance_score", item.get("score", 0.0))
                doc = item.get("document")
                if isinstance(doc, dict):
                    doc = doc.get("text")
                hits.append(RerankHit(index=idx, score=float(score), document=doc))
            hits.sort(key=lambda h: h.score, reverse=True)
            self._log_call("/v1/rerank", model, (time.perf_counter() - started) * 1000, "ok")
            return hits[:top_n]
        except GatewayError as exc:
            # /v1/rerank is custom code — a 404/5xx is expected. Fall back to cosine.
            logger.warning("rerank endpoint unavailable (%s); using cosine fallback", exc)
            return await self._cosine_rerank(model, query, documents, top_n, instruction)

    async def _cosine_rerank(
        self, model: str, query: str, documents: list[str], top_n: int, instruction: str | None
    ) -> list[RerankHit]:
        from app.llm.catalogue import EMBEDDING_MODEL
        from app.vectors import cosine

        q_text = f"{instruction} {query}" if instruction else query
        vectors = await self.embed(model=EMBEDDING_MODEL, texts=[q_text, *documents])
        q_vec, doc_vecs = vectors[0], vectors[1:]
        hits = [RerankHit(index=i, score=cosine(q_vec, dv), document=documents[i]) for i, dv in enumerate(doc_vecs)]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_n]

    async def models(self) -> list[str]:
        resp = await self._request("GET", "/v1/models")
        data = resp.json()
        return [item.get("id") for item in data.get("data", [])]

    async def health(self) -> ProviderHealth:
        try:
            await self._request("GET", "/health")
            try:
                model_ids = await self.models()
            except GatewayError:
                model_ids = []
            return ProviderHealth(
                provider="gateway", healthy=True,
                detail=f"gateway reachable at {self.base_url}", models=model_ids, degraded=self.degraded,
            )
        except GatewayError as exc:
            return ProviderHealth(
                provider="gateway", healthy=False,
                detail=f"unreachable: {exc}", degraded=self.degraded,
            )
