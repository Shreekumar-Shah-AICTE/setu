"""Tests for the BeyonData gateway client (app/llm/gateway.py).

All network I/O is simulated with httpx.MockTransport — no real calls are made.
"""
from __future__ import annotations

import httpx
import pytest

from app.llm.gateway import CircuitBreaker, GatewayError, OllamaGatewayClient


class Handler:
    """Programmable mock transport handler that records requests."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.script: dict[str, list] = {}   # path -> list of (status, json)
        self.default: dict[str, tuple] = {}  # path -> (status, json) repeated

    def program(self, path, responses=None, default=None):
        if responses is not None:
            self.script[path] = list(responses)
        if default is not None:
            self.default[path] = default

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.script.get(path):
            status, body = self.script[path].pop(0)
        elif path in self.default:
            status, body = self.default[path]
        else:
            status, body = 200, {}
        return httpx.Response(status, json=body)

    def count(self, path) -> int:
        return sum(1 for r in self.requests if r.url.path == path)


def make_client(handler: Handler, **overrides) -> OllamaGatewayClient:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OllamaGatewayClient(http_client=http_client, backoff_base=0.001)
    client.api_key = overrides.get("api_key", "test-key")
    client.auth_scheme = overrides.get("auth_scheme", "bearer")
    client.auth_header = overrides.get("auth_header", "Authorization")
    client.max_retries = overrides.get("max_retries", 3)
    client.fallback_enabled = overrides.get("fallback_enabled", True)
    client.breaker = CircuitBreaker(overrides.get("threshold", 5), overrides.get("reset", 60))
    return client


CHAT_OK = {"choices": [{"message": {"content": '{"department":"ENERGY"}'}}],
           "usage": {"prompt_tokens": 10, "completion_tokens": 3}}


async def test_chat_request_shape_and_auth():
    h = Handler()
    h.program("/v1/chat/completions", default=(200, CHAT_OK))
    client = make_client(h)
    res = await client.chat(model="gemma4:12b", messages=[{"role": "user", "content": "hi"}], json_mode=True)
    assert res.content == '{"department":"ENERGY"}'
    assert res.provider == "gateway"
    req = h.requests[-1]
    assert req.url.path == "/v1/chat/completions"
    assert req.headers.get("Authorization") == "Bearer test-key"
    import json
    body = json.loads(req.content)
    assert body["model"] == "gemma4:12b"
    assert body["response_format"] == {"type": "json_object"}
    await client.aclose()


async def test_embeddings_parse():
    h = Handler()
    h.program("/v1/embeddings", default=(200, {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}))
    client = make_client(h)
    out = await client.embed(model="bge-m3:latest", texts=["a", "b"])
    assert out == [[0.1, 0.2], [0.3, 0.4]]
    import json
    body = json.loads(h.requests[-1].content)
    assert body["input"] == ["a", "b"]
    await client.aclose()


async def test_retry_then_success():
    h = Handler()
    h.program("/v1/chat/completions", responses=[(503, {}), (503, {}), (200, CHAT_OK)])
    client = make_client(h, max_retries=3)
    res = await client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert res.provider == "gateway"
    assert h.count("/v1/chat/completions") == 3  # two failures + one success
    await client.aclose()


async def test_fallback_to_mock_when_exhausted():
    h = Handler()
    h.program("/v1/chat/completions", default=(500, {}))
    client = make_client(h, max_retries=2, fallback_enabled=True)
    res = await client.chat(
        model="m",
        messages=[{"role": "user", "content": "SETU_ARBITER_PROTOCOL_V1\nCANDIDATES: ENERGY=0.5"}],
    )
    assert res.degraded is True
    assert "fallback" in res.provider
    assert client.degraded is True
    await client.aclose()


async def test_no_fallback_raises():
    h = Handler()
    h.program("/v1/chat/completions", default=(500, {}))
    client = make_client(h, max_retries=1, fallback_enabled=False)
    with pytest.raises(GatewayError):
        await client.chat(model="m", messages=[{"role": "user", "content": "x"}])
    await client.aclose()


async def test_circuit_breaker_opens():
    h = Handler()
    h.program("/v1/embeddings", default=(503, {}))
    client = make_client(h, max_retries=0, threshold=3, fallback_enabled=False)
    # Three failing calls trip the breaker.
    for _ in range(3):
        with pytest.raises(GatewayError):
            await client.embed(model="m", texts=["x"])
    assert client.breaker.is_open()
    # Next call short-circuits without hitting the transport.
    before = h.count("/v1/embeddings")
    with pytest.raises(GatewayError):
        await client.embed(model="m", texts=["y"])
    assert h.count("/v1/embeddings") == before
    await client.aclose()


async def test_rerank_404_falls_back_to_cosine():
    h = Handler()
    h.program("/v1/rerank", default=(404, {}))
    h.program("/v1/embeddings", default=(200, {"data": [
        {"embedding": [1.0, 0.0]},  # query
        {"embedding": [1.0, 0.0]},  # doc0 (identical -> top)
        {"embedding": [0.0, 1.0]},  # doc1 (orthogonal)
    ]}))
    client = make_client(h)
    hits = await client.rerank(model="rr", query="q", documents=["d0", "d1"], top_n=2)
    assert hits[0].index == 0
    assert hits[0].score > hits[1].score
    await client.aclose()


async def test_health_reports_models():
    h = Handler()
    h.program("/health", default=(200, {"status": "ok"}))
    h.program("/v1/models", default=(200, {"object": "list", "data": [{"id": "bge-m3:latest"}, {"id": "gemma4:12b"}]}))
    client = make_client(h)
    health = await client.health()
    assert health.healthy is True
    assert "bge-m3:latest" in health.models
    await client.aclose()


def test_auth_scheme_variants():
    h = Handler()
    client = make_client(h, auth_scheme="header", auth_header="X-API-Key")
    assert client._headers().get("X-API-Key") == "test-key"
    client.auth_scheme = "query"
    client.auth_header = "Authorization"
    assert client._params() == {"api_key": "test-key"}
    client.auth_scheme = "none"
    assert "Authorization" not in client._headers()
