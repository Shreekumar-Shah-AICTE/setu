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
HTMX vs React, macro-F1 vs accuracy, business-hours SLA) are added in their
respective phases._

---

## 4. The mock embedding is an honest lexical approximation, not semantic

**Chosen.** The default `MockLLMClient.embed` uses the feature-hashing trick over
word unigrams/bigrams and intra-word character 3-grams, producing deterministic
1024-dimensional unit vectors — the same dimensionality as bge-m3, so swapping
providers needs no schema change.

**Considered.** Shipping a tiny real model, or leaving embeddings stubbed.

**Why.** It gives *genuine lexical similarity* (texts sharing words and character
patterns land near each other) with zero network, zero weights and full
determinism, so the pipeline is honestly exercised offline. It is **not**
semantic: it cannot tell that "power cut" and "વીજળી ગુલ" mean the same thing
unless they share characters. Concretely, a grievance whose only routing signal
is an inflected token such as `વીજપોლનો` (with the keyword `વીજપોલ` fused into a
suffix) is under-scored, and the blunt OTHER-threshold can send it to review.
This is expected and is quantified by the ablation harness (§9) and the Phase-12
real-embedding run — both of which show the semantic stage improving materially
when bge-m3 replaces the hash.

**What would change it.** Nothing for the offline default; in production
`LLM_PROVIDER=gateway` uses bge-m3 and the hash disappears entirely.

---

## 5. An explicit OTHER bucket rather than force-fitting

**Chosen.** An eleventh department, OTHER, with no keywords and no centroid.
Grievances with zero lexical hits and weak semantics are routed here (and queued
for review) rather than forced into the nearest wrong department.

**Considered.** Always picking the argmax department.

**Why.** The client's list omits Revenue, Health, Education, Water Supply and
Roads & Buildings. A "primary school has no teacher" complaint has no honest home
among the ten, and pretending it is (say) COTTAGE destroys trust and pollutes the
per-department metrics. OTHER keeps unmatched grievances *accountable* and makes
the review queue the place where new departments/keywords are discovered.

**What would change it.** Adding the missing departments with their own keyword
sets would shrink OTHER to a true residual.

---

## 6. Marker-first language detection for romanised Gujarati

**Chosen.** When Latin script dominates, check the romanised-Gujarati marker
list *before* the English word list, so "Gujlish" like `gaam ma light nathi
aavti` is detected as `gu-latn` even though it contains English-looking tokens
(`light`, `transformer`).

**Considered.** The literal spec ordering (English first).

**Why.** Function words such as `nathi`, `chhe`, `aavti`, `gaam` are far more
diagnostic of romanised Gujarati than incidental English loanwords are of
English. Marker-first makes trap T11 detect correctly and then transliterate to
the right department. English-only text (no markers) still resolves to `en`.
