# Architecture

SETU is a server-rendered FastAPI application with a staged classification
pipeline, a provider-abstraction layer for all external I/O, and an
APScheduler-driven SLA engine.

## Request lifecycle

1. **Intake** (`POST /submit` or `POST /api/v1/grievances`) creates a
   `Grievance` (`RECEIVED`) and runs `app.classification.pipeline.intake_grievance`.
2. **Classification cascade** (`app/classification/`) produces a department,
   secondary departments, urgency, confidence and a Decision Trace.
3. **Deduplication** compares the new embedding against the last 30 days in the
   same district; a near-match becomes `DUPLICATE`.
4. **State transition** to `CLASSIFIED` or `NEEDS_REVIEW` via `app/state.py`
   (the only writer of `grievances.status`), appending a `grievance_events` row.
5. **Dispatch** (`app/routing/dispatcher.py`) picks an officer, computes the SLA
   deadline, creates three magic-link tokens and sends the bilingual email.
6. **Escalation** — the APScheduler sweep (`app/sla/scheduler.py`) escalates
   grievances past `sla_due_at`; officers can also forward manually.
7. **Tracking** — citizens follow `GET /track/{ref_no}`; admins inspect
   everything at `/admin`, including the Decision Trace.

## The two provider Protocols

```
LLMClient    (app/llm/base.py):    chat · embed · rerank · health · name
EmailProvider(app/email/base.py):  send
```

Implementations:

| Protocol | Default | Alternatives |
| --- | --- | --- |
| LLMClient | `MockLLMClient` (feature-hashed embeddings + rule-based arbiter) | `OllamaGatewayClient` (BeyonData), `LocalEmbeddingClient` (sentence-transformers) |
| EmailProvider | `ConsoleEmailProvider` (`.eml` + preview to `outbox/`) | `SmtpEmailProvider` (STARTTLS) |

Factories (`app/llm/factory.py`, `app/email/base.py`) select the implementation
from `LLM_PROVIDER` / `EMAIL_PROVIDER`. The gateway client adds retries with
backoff+jitter, a circuit breaker and transparent fallback to the mock so a
gateway outage never crashes the app (the admin UI shows an amber "degraded"
banner instead).

## Data model

Thirteen tables (`app/models.py`): `departments`, `keywords`, `officers`,
`grievances`, `grievance_events` (append-only audit), `classification_traces`
(explainability), `action_tokens`, `sla_policies`, `review_queue`,
`golden_samples`, `eval_runs`, `holidays`, `app_settings` (runtime config).
UUID string primary keys; JSON columns work identically on SQLite and Postgres.

## State machine

`app/state.py` defines `ALLOWED_TRANSITIONS: dict[Status, set[Status]]`. Statuses:
`RECEIVED, CLASSIFIED, NEEDS_REVIEW, ASSIGNED_L1, ACKNOWLEDGED_L1, ESCALATED_L2,
ACKNOWLEDGED_L2, ESCALATED_L3, RESOLVED, CLOSED, REOPENED, DUPLICATE, REJECTED`.
Every transition is validated and audited; illegal transitions raise
`InvalidTransitionError`.

## Vectors

`app/vectors.py` owns all similarity maths: an in-memory NumPy matrix of unit
embeddings, rebuilt on write, with cosine `search` and district/time-windowed
`find_similar` for deduplication. Migration path past ~100k rows: PostgreSQL +
pgvector (HNSW), a contained change because everything routes through this
module.

## Concurrency model

FastAPI endpoints and LLM calls are async (`httpx`); persistence is synchronous
SQLAlchemy. The scheduler is an `AsyncIOScheduler` running an idempotent sweep.
See `DECISIONS.md` §12 for the rationale.
