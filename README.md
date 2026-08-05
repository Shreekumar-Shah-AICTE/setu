# SETU — Smart Escalation & Triage Unit · સેતુ ("bridge")

> Citizen grievance intake → automatic department classification → officer email
> dispatch → SLA-driven escalation → public status tracking. Built for the
> Gujarat State Government departmental grievance-redressal model, in Gujarati,
> English and romanised "Gujlish".

**SETU runs fully offline.** The default configuration uses a real, deterministic
mock LLM provider — no API keys, no network, no Docker. Point one environment
variable at the BeyonData gateway to switch to production models.

## Quickstart (two commands)

```bash
pip install -r requirements.txt
make demo
```

`make demo` migrates the schema, seeds departments / keywords / officers /
holidays, simulates a realistic month of grievances, runs the evaluation
harness, and starts the server at <http://localhost:8000> (admin at `/admin`).

## The two switches

| Switch | Env var | Default | Alternative |
| --- | --- | --- | --- |
| LLM provider | `LLM_PROVIDER` | `mock` (offline, deterministic) | `gateway` (BeyonData), `local` (sentence-transformers) |
| Email | `EMAIL_PROVIDER` | `console` (writes `.eml` to `outbox/`) | `smtp` (Gmail app password) |

## Documentation

- `docs/architecture.md`, `docs/classification.md`, `docs/evaluation.md`, `docs/api.md`, `docs/operations.md`
- `HANDOFF.md` — the exact human steps to go to production
- `DECISIONS.md` — design decisions and the alternatives considered
- `DEMO_SCRIPT.md` — a timed 7-minute walkthrough

_This README is expanded with screenshots and the evaluation summary in the
documentation phase._
