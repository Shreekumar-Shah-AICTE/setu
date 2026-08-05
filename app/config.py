"""Application configuration.

All settings are read from environment variables (with an optional ``.env``
file for local development). There are **no secrets in this file** — only
defaults that are safe to commit. Secrets such as ``SECRET_KEY``,
``OLLAMA_GATEWAY_API_KEY`` and ``SMTP_PASSWORD`` must come from the environment.

The four classification-gating constants (alpha, confidence, margin, other
threshold) and the review/dedupe thresholds also live in the ``app_settings``
database table so an administrator can change them at runtime without a
restart. The values here are the *initial* values used to seed that table.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = directory that contains this ``app`` package's parent.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Application ----
    app_name: str = "SETU"
    app_env: str = "development"
    public_base_url: str = "http://localhost:8000"
    secret_key: str = "insecure-dev-key-change-me"

    # ---- Database ----
    database_url: str = "sqlite:///./setu.db"

    # ---- LLM provider ----
    llm_provider: str = "mock"  # mock | gateway | local

    # ---- BeyonData gateway ----
    ollama_gateway_base_url: str = "http://localhost:11434"
    ollama_gateway_auth_scheme: str = "bearer"  # bearer | header | query | none
    ollama_gateway_auth_header: str = "Authorization"
    ollama_gateway_api_key: str = ""
    ollama_gateway_connect_timeout: float = 10.0
    ollama_gateway_read_timeout: float = 120.0
    ollama_gateway_max_retries: int = 3
    ollama_gateway_circuit_fail_threshold: int = 5
    ollama_gateway_circuit_reset_seconds: float = 60.0
    llm_fallback_to_mock: bool = True

    # ---- Model catalogue (overridable) ----
    embedding_model: str = "bge-m3:latest"
    arbiter_model: str = "gemma4:12b"
    arbiter_model_xl: str = "gemma4:31b"
    json_model: str = "mistral-small3.2:latest"
    rerank_model: str = "dengcao/Qwen3-Reranker-8B:Q8_0"
    translate_model: str = "translategemma:12b"
    vision_model: str = "qwen2.5vl:7b"

    # ---- Local provider (Phase 12 / optional) ----
    local_embedding_model: str = "intfloat/multilingual-e5-small"

    # ---- Email ----
    email_provider: str = "console"  # console | smtp
    email_from: str = "SETU Grievance Cell <no-reply@setu.local>"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    # ---- Admin ----
    admin_username: str = "admin"
    admin_password: str = "setu-admin"

    # ---- SLA / scheduler ----
    sla_time_scale: float = 1.0
    sla_sweep_seconds: int = 60
    scheduler_enabled: bool = True

    # ---- Classification defaults (seed values for app_settings) ----
    classify_alpha: float = 0.45
    confidence_high: float = 0.62
    margin_min: float = 0.15
    other_threshold: float = 0.30
    review_threshold: float = 0.55
    semantic_temperature: float = 0.07
    dedupe_threshold: float = 0.92

    # ---- Paths ----
    outbox_dir: str = str(BASE_DIR / "outbox")
    data_dir: str = str(BASE_DIR / "data")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def outbox_path(self) -> Path:
        p = Path(self.outbox_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Tests may set environment variables before the first call, or clear the
    cache via ``get_settings.cache_clear()`` after mutating ``os.environ``.
    """
    return Settings()


# A module-level convenience handle. Prefer ``get_settings()`` in code that
# needs to react to environment changes (e.g. tests).
settings = get_settings()


def reload_settings() -> Settings:
    """Clear the settings cache and rebuild. Used by tests."""
    get_settings.cache_clear()
    global settings
    settings = get_settings()
    return settings
