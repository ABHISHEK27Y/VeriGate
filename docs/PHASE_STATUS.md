# Research-build phase status

The two project briefs define the following sequence. A phase is only complete when
its evidence and checks exist; a working component is not a finished research claim.

| Phase | Required outcome | Current status |
|---|---|---|
| 0 — baseline and hygiene | Honest README/report, generated tables, green CI | Complete in the prior commit; current local checks remain green. |
| 1 — dataset and protocol | Public sources, answer-aware reviewed labels, grouped splits, fair baselines, CIs, filling-cache replay | **Factoid proxy complete; independent answer review open.** NQ-Open mined gold-answer-match pairs, hard negatives, provenance, grouped five-seed splits and oracle-answer chronological replay exist. The 2,000-row review queue remains optional and entirely blank; it contributes no evidence. Large-cache retrieval and generated-answer labels remain. |
| 2 — learned accept policy | Trained/calibrated model, ablations, transfer and opt-in gateway use | **Research experiment complete; deployment open.** NQ gold-answer-match logistic model includes local bidirectional NLI and structural features; five-seed intervals, a no-NLI ablation, static/adaptive baselines and separate PAWS transfer exist. The curated NQ split is easy and PAWS transfer poor. No trained gold model is wired into the gateway. |
| 3 — risk control | Correct bound, artifact, held-out resampling and shift study | **Calibration study complete; deployment guarantee open.** The exact bound and finite-grid correction were rerun on disjoint NQ gold calibration groups for 1%, 2%, and 5%. Every seed selected reject-all. Oracle alias labels do not establish generated-answer safety. |
| 4 — answer shadow checks and drift | Async fresh-answer checks, tenant controller, drift replay | **Partial.** The opt-in shadow sampler records cached question and answer plus a fresh answer. A pinned local triple judge exists, but failed gold validation and produced no model-judged rows: the review queue has blank answers and shadow is off. No reviewed outcome set, drift replay or active controller exists. No real-provider shadow calls were made. See `SHADOW_REVIEW.md`. |
| 5 — volatility and TTL | Labelled volatility corpus, classifier and staleness/hit-rate study | Not started. Existing keyword rules remain. |
| 6 — provider routing quality | Real cheap/strong answers and cost/quality frontier | Not started; requires authorized provider usage. Historical router cost ratios are illustrative. |
| 7 — scale and report | 1M-entry benchmark where feasible, measured HNSW recall/latency, full report | **Partial.** The report now includes generated tables for the learned pair proxy, filling-cache replay and synthetic risk study, plus explicit threats to validity. The older 1k–10k backend comparison is separate engineering evidence; 1M-entry HNSW recall/latency and crossover remain unmeasured. |

The new factoid proxy supplies oracle reference-answer comparisons for each
accepted replay hit, including cross-pair hits. The experimental judge and
risk bound both produced negative results. None establishes the rate of
incorrect generated cached answers. `CACHE_MATCH_MODE=exact` remains the default.
No paid provider calls were made. Untracked `audit/` content was not modified.
