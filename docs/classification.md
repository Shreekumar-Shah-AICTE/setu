# Classification methodology

The classifier is a **cascade**: cheap, precise stages first; the expensive LLM
only for the ambiguous minority. Each stage lives in `app/classification/` and
is independently testable.

## Stage 0 — Normalisation (`normalize.py`)

A pure function. In order: Unicode NFC → whitespace collapse → Gujarati digit
(૦–૯) to ASCII → **variant folding** (`ઈ→ઇ`, `ઊ→ઉ`, matra `ી→િ`, `ૂ→ુ`, strip
ZWJ/ZWNJ, lowercase ASCII) → punctuation strip (keeping intra-word hyphens) →
language detection (`gu | en | gu-latn | mixed`) → transliteration expansion for
romanised text.

Folding makes `લાઈટો` and `લાઇટ` share a stem (trap **T4**). The stray space in
the source keyword `હાઈ- ટેન્શન લાઇન` (trap **T6**) is handled because the
hyphen is not intra-word once the space is present, so it is stripped
consistently for both the keyword and the grievance.

Romanised "Gujlish" (trap **T11**) is detected by a marker word list and
expanded via `data/translit.yaml` (60+ mappings), e.g. `light → લાઇટ`,
`transformer → ટ્રાન્સફોર્મર`, so downstream stages match it.

## Stage 1 — Lexical matcher (`lexical.py`)

An Aho–Corasick automaton over all active keywords in folded form, with two
rules:

- **Whole-token boundaries** — a match must start at a token start and end at a
  token end. This stops `ઉદ્યોગ` matching inside `મત્સ્યોદ્યોગ` (trap **T2**).
- **Longest match wins** — overlapping matches resolve to the one spanning more
  tokens, so `કુટિર ઉદ્યોગ` (2 tokens → COTTAGE) beats the embedded `ઉદ્યોગ`
  (1 token → INDUSTRY) (trap **T1**).

Score per department = `Σ weight × token_count` over surviving matches,
normalised to sum 1.0. Every hit records character offsets for the Decision
Trace highlighter. The match runs in well under 5 ms (asserted in tests).

## Stage 2 — Semantic matcher (`semantic.py`)

Each department has a **centroid**: the L2-normalised mean of the embeddings of
its keywords plus every **dev-split** golden sample labelled to it. Classifying
computes the cosine similarity to each centroid and applies a softmax
(temperature 0.07) to produce a distribution. OTHER has no centroid; it is
assigned by fusion when everything else scores low. Centroids are recomputed
whenever a human corrects a classification.

## Stage 3 — Fusion and gating (`fusion.py`)

```
fused[d] = ALPHA · lexical[d] + (1 − ALPHA) · semantic[d]      # ALPHA = 0.45
```

Gate (constants are runtime-editable in `/admin/settings`):
- No lexical hits **and** top semantic < `OTHER_THRESHOLD` (0.30) → **OTHER** +
  review.
- `top1 ≥ CONFIDENCE_HIGH` (0.62) **and** margin ≥ `MARGIN_MIN` (0.15) →
  **accept** (Stage 2), skip the arbiter.
- Otherwise → **Stage 4 arbiter**.

## Stage 4 — LLM arbiter (`arbiter.py`)

Invoked only on the uncertain minority. The prompt carries the grievance, the
bilingual department list, the lexical hits, the top-3 fused candidates and the
trap disambiguation rules. The model (`gemma4:12b`, temperature 0, JSON mode)
returns a strict schema validated by Pydantic. Parsing is defensive: strip
`<think>` blocks and markdown fences, extract the first balanced `{...}`,
validate; on failure retry once with a repair prompt; on a second failure fall
back to the fused winner and mark the trace `degraded`. If the arbiter's
confidence < `REVIEW_THRESHOLD` (0.55) the grievance goes to `NEEDS_REVIEW`.

## Urgency & deduplication (parallel)

`urgency.py` scans for life-safety signals (`data/urgency.yaml`): a CRITICAL
match skips L1, assigns directly to L2, sets a 6-hour SLA and prefixes the
subject with `[URGENT]`. `dedupe.py` marks a grievance `DUPLICATE` when its
embedding exceeds the similarity threshold against the last 30 days in the same
district.

## Explainability

Every classification persists a `ClassificationTrace` with the normalized text,
per-stage scores, keyword hits with offsets, the arbiter's raw + parsed output,
the chosen department, confidence, margin, decided-by-stage, degraded flag,
provider and per-stage latency — rendered as the admin **Decision Trace** panel.
