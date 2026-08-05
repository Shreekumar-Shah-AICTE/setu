"""Shared pytest fixtures.

An isolated SQLite database is created in a temp directory and seeded once per
session. The environment is configured for the offline mock provider and the
console email provider before any application module is imported.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="setu-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMAIL_PROVIDER"] = "console"
os.environ["OUTBOX_DIR"] = str(_TMP / "outbox")
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine, session_scope  # noqa: E402
from app.seed import seed_all  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema_and_seed():
    import asyncio

    from app.classification.semantic import compute_centroids
    from app.llm.factory import get_llm_client

    Base.metadata.create_all(engine)
    with session_scope() as db:
        seed_all(db)
        asyncio.run(compute_centroids(db, get_llm_client()))
    yield


@pytest.fixture
def db():
    """Function-scoped session that rolls back so tests stay isolated."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tmp_outbox() -> Path:
    p = _TMP / "outbox"
    p.mkdir(parents=True, exist_ok=True)
    return p
