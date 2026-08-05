# Operations

## Running

```bash
make demo      # migrate → seed → simulate → evaluate → serve  (zero setup)
make serve     # serve only (HOST/PORT overridable: make serve PORT=8080)
make run       # dev server with autoreload
make test      # pytest
make preflight # readiness report (non-zero exit on hard failure)
```

## Configuration

All configuration is environment-driven (`app/config.py`); copy `.env.example`
to `.env`. Key variables: `LLM_PROVIDER`, `EMAIL_PROVIDER`, `DATABASE_URL`,
`SECRET_KEY`, `ADMIN_USERNAME`/`ADMIN_PASSWORD`, `PUBLIC_BASE_URL`,
`SLA_TIME_SCALE`, `SLA_SWEEP_SECONDS`, `SCHEDULER_ENABLED`. The classification
thresholds and SLA hours are also editable at runtime in `/admin/settings`
(stored in `app_settings` / `sla_policies`) and take effect without a restart.

## Database

SQLite by default (`setu.db`, WAL mode). PostgreSQL via
`DATABASE_URL=postgresql+psycopg2://…` (add `psycopg2-binary`). Schema is managed
by Alembic:

```bash
python -m alembic upgrade head
python -m alembic revision --autogenerate -m "message"
```

## Scheduler & SLA

An `AsyncIOScheduler` sweeps every `SLA_SWEEP_SECONDS` (default 60) and once ~5s
after startup. It escalates grievances past `sla_due_at` in non-terminal states;
the escalation is idempotent (uniqueness on `(grievance_id, to_level)` + a status
precondition). For a live demo set `SLA_TIME_SCALE=3600` (72h → 72s).

## Email outbox

With `EMAIL_PROVIDER=console`, every send writes `outbox/<timestamp>_<kind>_<id>.eml`
(valid RFC-822) plus an `.html` preview with live, clickable magic links. Clean
with `make clean`.

## Logging

Structured stdlib logging. Every gateway call logs model, endpoint, latency and
outcome; every SLA sweep and email send is logged. Classification latency is
recorded per stage on each trace.

## Backups & data reset

```bash
make fresh     # remove caches AND drop the SQLite DB (destructive)
python -m app.cli seed        # reseed reference data + centroids
python -m app.cli simulate    # regenerate demo history (deterministic, seed 42)
```

## Health monitoring

`GET /health` (app/DB/provider/scheduler) and `GET /api/v1/health` for probes.
The admin banner turns amber when the gateway is unreachable and SETU is running
on the mock fallback.
