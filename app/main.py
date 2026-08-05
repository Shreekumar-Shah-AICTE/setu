"""SETU FastAPI application entry point.

Phase 0 provides a booting app with a rich ``/health`` endpoint. Later phases
attach routers (public, actions, admin, api), the APScheduler-based SLA sweeper
and the Jinja2 template environment. The wiring here is intentionally written
so that each subsystem can be imported lazily and degrade gracefully if it is
not yet available.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)
logger = logging.getLogger("setu")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop background subsystems with the app lifecycle."""
    settings = get_settings()
    logger.info("Starting %s (env=%s, provider=%s, email=%s)",
                settings.app_name, settings.app_env, settings.llm_provider,
                settings.email_provider)

    scheduler = None
    if settings.scheduler_enabled:
        try:
            from app.sla.scheduler import start_scheduler

            scheduler = start_scheduler(app)
            logger.info("SLA scheduler started (sweep every %ss)", settings.sla_sweep_seconds)
        except Exception as exc:  # pragma: no cover - defensive; scheduler optional
            logger.warning("Scheduler not started: %s", exc)

    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("SLA scheduler stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SETU — Smart Escalation & Triage Unit",
        description=(
            "Citizen grievance intake, automatic department classification, "
            "email dispatch, SLA-driven escalation and public status tracking."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Static assets (all vendored — no CDN).
    static_dir = BASE_DIR / "app" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---- Routers (attached as they are implemented) ----
    for module_name, attr in (
        ("app.routers.public", "router"),
        ("app.routers.actions", "router"),
        ("app.routers.admin", "router"),
        ("app.routers.api", "router"),
    ):
        try:
            module = __import__(module_name, fromlist=[attr])
            app.include_router(getattr(module, attr))
        except ModuleNotFoundError:
            # Router not implemented yet (earlier build phases).
            logger.debug("Router %s not present yet", module_name)

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        """Liveness/readiness probe: app, DB, provider and scheduler status."""
        settings = get_settings()
        payload: dict = {
            "status": "ok",
            "app": settings.app_name,
            "env": settings.app_env,
            "version": "1.0.0",
        }

        # Database check
        try:
            from sqlalchemy import text

            from app.db import engine

            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            payload["database"] = {"status": "ok", "url_scheme": settings.database_url.split(":", 1)[0]}
        except Exception as exc:  # pragma: no cover - defensive
            payload["status"] = "degraded"
            payload["database"] = {"status": "error", "detail": str(exc)}

        # Provider health (best-effort; provider layer may not exist in phase 0)
        try:
            from app.llm.factory import get_llm_client

            client = get_llm_client()
            health_info = await client.health()
            payload["provider"] = {
                "name": health_info.provider,
                "healthy": health_info.healthy,
                "detail": health_info.detail,
            }
        except Exception as exc:
            payload["provider"] = {"name": settings.llm_provider, "healthy": None, "detail": str(exc)}

        # Scheduler
        scheduler = getattr(app.state, "scheduler", None)
        payload["scheduler"] = {"running": bool(scheduler and getattr(scheduler, "running", False))}

        return payload

    return app


app = create_app()
