# SETU — Handoff

This is the most operationally important file: **exactly** what a human must do
to take SETU from the offline demo to production. Every step lists the precise
`.env` lines and an estimated effort.

The defaults already work with zero setup (`pip install -r requirements.txt &&
make demo`). The steps below are only needed to connect real infrastructure.

---

## 1. Connect the BeyonData AI gateway (~2 min)

Set these in `.env` (copy from `.env.example`):

```dotenv
LLM_PROVIDER=gateway
OLLAMA_GATEWAY_BASE_URL=https://<your-gateway-host>
OLLAMA_GATEWAY_AUTH_SCHEME=bearer          # bearer | header | query | none
OLLAMA_GATEWAY_AUTH_HEADER=Authorization
OLLAMA_GATEWAY_API_KEY=<your-gateway-api-key>
LLM_FALLBACK_TO_MOCK=true                  # keep true so a gateway outage never crashes the demo
```

Then **re-seed** so the centroids are fit with the gateway's `bge-m3`
embeddings (they differ from the mock's, and preflight will warn if the
dimensionality changed):

```bash
python -m app.cli seed
python scripts/preflight.py
```

Model IDs are pinned in `app/llm/catalogue.py` and overridable via env
(`EMBEDDING_MODEL`, `ARBITER_MODEL`, …). Only `/v1/` endpoints are called. The
custom `/v1/rerank` endpoint is optional — a 404/5xx is caught and falls back to
cosine ordering.

## 2. Enable real email (~5 min)

For Gmail, create an **App Password** (Google Account → Security → 2-Step
Verification → App passwords → generate a 16-character password). Then:

```dotenv
EMAIL_PROVIDER=smtp
EMAIL_FROM=SETU Grievance Cell <your-address@gmail.com>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-address@gmail.com
SMTP_PASSWORD=<16-char app password>
SMTP_USE_TLS=true
```

Send yourself a test grievance from `/` and confirm the officer email arrives.
Replies/escalations set `In-Reply-To`/`References` from the grievance's
`root_message_id`, so a grievance stays as one Gmail thread.

## 3. Replace the placeholder officer directory (~10 min)

`data/officers.seed.yaml` is clearly marked `# PLACEHOLDER DIRECTORY`. Replace
the 33 fictional officers (`*@example.gov.in`) with the real taluka/district/
state officers per department and level, then re-seed:

```bash
python -m app.cli seed
```

Or edit officers live in the admin console at `/admin/officers`.

## 4. Run preflight and read the output (~1 min)

```bash
python scripts/preflight.py
```

A hard failure exits non-zero. A **loud warning fires if the embedding
dimensionality ≠ 1024**, because that invalidates the cached centroids and
requires a re-seed.

## 5. Production hardening (as needed)

```dotenv
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
ADMIN_USERNAME=<change me>
ADMIN_PASSWORD=<change me>
PUBLIC_BASE_URL=https://grievance.gujarat.gov.in
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/setu   # optional; pip install psycopg2-binary
```

Run behind a TLS-terminating reverse proxy. For PostgreSQL, run
`python -m alembic upgrade head` against the new database before seeding.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Admin banner shows "gateway degraded" | Gateway unreachable; running on mock fallback | Check `OLLAMA_GATEWAY_BASE_URL`/key; `python scripts/preflight.py` |
| Preflight warns "dimensionality ≠ 1024" | Provider embeddings differ from cached centroids | `python -m app.cli seed` to re-fit centroids |
| No officer email arrives (SMTP) | Wrong app password / TLS port | Use port 587 + STARTTLS + a Gmail **App Password**, not the account password |
| `/action/<token>` says "expired" | Token past `sla_due_at + 48h` | Re-dispatch from the admin grievance detail (correct & reassign) |
| Escalations not firing | Scheduler disabled | Set `SCHEDULER_ENABLED=true`; it sweeps every `SLA_SWEEP_SECONDS` |
| Live escalation demo too slow | Real time scale | Set `SLA_TIME_SCALE=3600` (72h → 72s) and restart |
| Everything classifies to OTHER | Centroids not seeded | `python -m app.cli seed` |
| Grievance marked DUPLICATE unexpectedly | Very similar text in the same district within 30 days | Lower `DEDUPE_THRESHOLD` in `/admin/settings` |
| `make demo` port already in use | Port 8000 busy | `make serve PORT=8080` |

## Known limitations

- The default mock embedding is a **lexical approximation**, not semantic. It is
  honest and offline, but real semantic quality needs `LLM_PROVIDER=gateway`
  (bge-m3). Quantified in `docs/evaluation.md`.
- Movable festival dates in `data/holidays.yaml` are approximate — reconcile
  with the official Gujarat holiday circular.
- The officer directory is placeholder data (see step 3).
