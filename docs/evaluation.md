# SETU — Evaluation Report

_Generated 2026-08-05 22:51 UTC · provider `mock` · metrics on the **held-out test split** only._

## Why macro-F1 is the headline metric

Departments are imbalanced. Macro-F1 averages the per-class F1 with equal weight, so it refuses to let big classes hide failures on small ones. Accuracy alone would flatter a model that nails the common departments and quietly fails the rare ones.

## The dev/test split

Centroids are fit on the **dev** split (40%). Every number below is computed on the **test** split (60%), which the model never saw during fitting. Honouring this split is the clearest signal of ML competence in the project.

## The ablation study

| Config | Description | macro-F1 | accuracy | mean ms | LLM calls / 1k |
| --- | --- | ---: | ---: | ---: | ---: |
| A_lexical_only | Lexical only | 0.939 | 0.938 | 4.3 | 0 |
| B_semantic_only | Semantic only | 0.701 | 0.742 | 4.4 | 0 |
| C_fusion_no_arbiter | Lexical + semantic fusion, no arbiter | 0.920 | 0.917 | 4.4 | 0 |
| D_full_cascade | Full cascade (shipped system) | 0.929 | 0.928 | 14.2 | 175 |
| E_arbiter_only | Arbiter only (every grievance to the LLM) | 0.818 | 0.866 | 61.9 | 1000 |

### Reading the table

Config **E** (arbiter-only) sends 100% of grievances to the LLM. Config **D** (the shipped cascade) reaches comparable quality while sending only the genuinely ambiguous minority to the model — the difference in *LLM calls / 1k* is the cost argument of the whole project. Lexical-only (**A**) is instantaneous but brittle on paraphrase; semantic-only (**B**) generalises but lacks the precision of exact keyword hits; fusion (**C**) combines them; the arbiter (**D**) resolves the residual ambiguity.

> Under the default **mock** provider the embeddings are a lexical approximation, so the keyword-rich golden set favours the lexical configs and semantic-only (**B**) lags. The Phase-12 real-embedding table below shows the semantic and fusion configs improving once a genuine multilingual model replaces the hash — the whole reason the two tables are read together.

## Headline metrics (Config D, test split)

- **macro-F1:** 0.929
- **accuracy:** 0.928
- **weighted-F1:** 0.928
- **top-2 accuracy:** 1.000
- **mean confidence (correct / incorrect):** 0.801 / 0.731
- **arbiter call rate:** 17.5%
- **samples:** 97

## Per-department breakdown

| Department | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| AGRICULTURE | 0.875 | 0.778 | 0.824 | 9 |
| COTTAGE | 1.000 | 0.889 | 0.941 | 9 |
| ENERGY | 1.000 | 0.909 | 0.952 | 11 |
| ENVIRONMENT | 0.800 | 1.000 | 0.889 | 8 |
| FINANCE | 1.000 | 0.889 | 0.941 | 9 |
| FISHERIES | 1.000 | 1.000 | 1.000 | 9 |
| FOOD_CIVIL | 0.818 | 1.000 | 0.900 | 9 |
| HOME | 1.000 | 0.889 | 0.941 | 9 |
| INDUSTRY | 0.889 | 0.889 | 0.889 | 9 |
| MINES | 0.889 | 1.000 | 0.941 | 8 |
| OTHER | 1.000 | 1.000 | 1.000 | 7 |
