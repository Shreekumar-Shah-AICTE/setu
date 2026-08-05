# SETU — Design Decisions

This is the design-defence document. For each decision we record **what was
chosen**, **what else was considered**, **why**, and **what would change the
answer**. Decisions are appended as the build progresses.

---

## 1. A three-stage cascade (lexical → semantic → LLM arbiter) rather than LLM-only

**Chosen.** Classify with a cheap Aho–Corasick lexical matcher and a vector
similarity stage, and only escalate the genuinely ambiguous minority (15–30%)
to an LLM arbiter.

**Considered.** Sending every grievance straight to an LLM.

**Why.** The ablation study (§9) quantifies it: LLM-only ("Config E") matches or
slightly beats the cascade on accuracy but at roughly 5–7× the latency and cost,
because it calls the model on 100% of traffic. The cascade reaches near-parity
quality while calling the model only on the ambiguous slice. That trade-off is
the engineering argument of the whole project.

**What would change it.** If the gateway were free and instantaneous, or if
lexical/semantic accuracy were poor on the domain, LLM-only would win.

---

## 2. SQLite by default, PostgreSQL supported by the same code

**Chosen.** `DATABASE_URL=sqlite:///./setu.db` out of the box.

**Considered.** Requiring PostgreSQL from the start.

**Why.** Zero-setup is a hard requirement: `pip install` then `make demo` on a
fresh machine, no Docker. SQLAlchemy keeps the code database-agnostic, so the
same models run on Postgres by changing one URL.

**What would change it.** Concurrency beyond a single node, or dataset sizes
where SQLite's write locking hurts, push you to Postgres (see decision 3).

---

## 3. NumPy cosine over an in-memory matrix rather than pgvector

**Chosen.** Store embeddings as JSON arrays; do similarity search with NumPy
over a matrix rebuilt on write, all behind `app/vectors.py`.

**Considered.** PostgreSQL + `pgvector` with an HNSW index.

**Why.** Portability and zero-setup. At the scale of a demo / pilot (thousands
of rows) a brute-force NumPy cosine is microseconds and needs no extension.

**What would change it.** Past ~100k rows, move to Postgres + pgvector with an
HNSW index. Because every vector operation is confined to one module, that is a
contained change — nothing else in the codebase touches raw vectors.

---

_Further decisions (APScheduler vs Celery, magic links vs officer accounts,
HTMX vs React, macro-F1 vs accuracy, the mock embedding's honest limitations,
the OTHER bucket, business-hours SLA) are added in their respective phases._
