"""Model catalogue for the BeyonData OpenAI-compatible gateway.

These are the canonical model IDs available on the gateway. Every one is
overridable via the environment (see :mod:`app.config`), so nothing here is a
hard dependency. Only ``/v1/`` endpoints are ever called — never a
model-specific path like ``/qwen3.6/chat`` — so the client stays portable.

Additional models known to be available on the gateway (not used by default):
    qwen3-embedding:8b-fp16, qwen3-embedding:latest, nomic-embed-text:latest,
    llava:7b, llava:13b, qwen2.5:32b-instruct, qwen3.6:latest,
    gemma4:31b-ctx32k, gemma4:26b, gemma4:e4b, gemma4:e2b,
    deepseek-r1:14b-qwen-distill-fp16, deepseek-r1:8b, llama3.2:1b, llama3.1:8b.
"""
from __future__ import annotations

# 1024-dim, 8192 ctx, 100+ languages — the production embedding model.
EMBEDDING_MODEL = "bge-m3:latest"

# Default reasoning model for the arbiter.
ARBITER_MODEL = "gemma4:12b"

# Larger reasoning model for hard cases.
ARBITER_MODEL_XL = "gemma4:31b"

# Fallback model if JSON reliability of the default is poor.
JSON_MODEL = "mistral-small3.2:latest"

# Reranker (custom /v1/rerank endpoint on the gateway).
RERANK_MODEL = "dengcao/Qwen3-Reranker-8B:Q8_0"

# Translation model.
TRANSLATE_MODEL = "translategemma:12b"

# Vision model.
VISION_MODEL = "qwen2.5vl:7b"

# The embedding dimensionality the schema and centroids assume.
EMBEDDING_DIM = 1024

__all__ = [
    "EMBEDDING_MODEL",
    "ARBITER_MODEL",
    "ARBITER_MODEL_XL",
    "JSON_MODEL",
    "RERANK_MODEL",
    "TRANSLATE_MODEL",
    "VISION_MODEL",
    "EMBEDDING_DIM",
]
