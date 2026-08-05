# AGENTS.md — conventions for AI agents working in this repo

This file orients future AI agents (and humans) contributing to SETU.

## Golden rules
- **No stubs.** Every function is fully implemented. No `TODO`, `pass`,
  `NotImplementedError` or placeholder returns in `app/`. If something genuinely
  cannot be done, implement a working fallback and record it in `HANDOFF.md`.
- **No secrets, ever.** Everything sensitive comes from environment variables;
  `.env.example` holds placeholders. Never commit a real `.env`, key or password.
- **Offline by default.** The default `LLM_PROVIDER=mock` and
  `EMAIL_PROVIDER=console` must keep working with no network. `make demo` and
  `pytest` must never require a download beyond `requirements.txt`.
- **No CDN, no Node build.** CSS/JS/fonts are vendored in `app/static/`. Server-
  rendered HTML only.

## Architecture invariants
- `app/state.py` is the **only** place that writes `grievances.status`. Use
  `transition()`; illegal transitions raise `InvalidTransitionError`.
- `grievance_events` is append-only — never update or delete a row.
- All vector maths lives behind `app/vectors.py`.
- All external I/O goes through a provider Protocol: `app/llm/base.py`
  (`LLMClient`) and `app/email/base.py` (`EmailProvider`). Add providers, don't
  scatter `httpx`/`smtplib` calls.
- The classification cascade is staged and independently testable:
  `normalize → lexical → semantic → fusion → arbiter` in `app/classification/`.
- Runtime-editable knobs live in the `app_settings` table via
  `app/runtime_config.py`; read them per request so admin edits apply without a
  restart.

## Data contracts
- `data/departments.yaml` keyword strings are reproduced **exactly** (including
  inconsistent spellings and the stray space in `હાઈ- ટેન્શન લાઇન`). Do not
  "correct" them.
- The twelve traps in `tests/test_traps.py` are the most important tests. Keep
  them green.
- The golden set is split 40% dev / 60% test. Fit only on dev; report only on
  test.

## Workflow
- Build in phase order; keep `pytest` green before committing.
- Prefer new commits over amending; commit after each logical unit.
- Run `python scripts/preflight.py` after changing providers or centroids.
- Regenerate the golden set with `python scripts/generate_golden_set.py` (it is
  deterministic under seed 42).

## Tests
- `pytest` must exit 0 with 100+ tests. Never report completion with failures.
- Gateway tests must use `httpx.MockTransport` — never a real network call.
- Tests that mutate shared seeded state (e.g. centroids) must restore it.

## Style
- Python 3.11+, typed SQLAlchemy 2.0, Pydantic v2. Keep functions focused and
  fully implemented. Comment the non-obvious ("why", not "what").
