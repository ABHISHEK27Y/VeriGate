# Research-build phase status

The two project briefs define the following sequence. A phase is only complete when
its evidence and checks exist; a working component is not a finished research claim.

| Phase | Required outcome | Current status |
|---|---|---|
| 0 — baseline and hygiene | Honest README/report, generated tables, green CI | Complete in the prior commit; current local checks remain green. |
| 1 — dataset and protocol | Public sources, answer-aware reviewed labels, grouped splits, fair baselines, CIs, filling-cache replay | **Partial.** Public pair sources, provenance, grouped splits, five-seed held-out pair proxy results and CIs exist. Independent answer labels, stream replay, density evaluation and retrieval metrics do not. |
| 2 — learned accept policy | Trained/calibrated model, ablations, transfer and opt-in gateway use | Not started. Shipping a model trained only on pair labels as an answer-reuse policy would be unsafe. |
| 3 — risk control | Correct bound, artifact, held-out resampling and shift study | **Primitive only.** A tested exact binomial upper bound and corrected threshold search exist. No answer-labelled calibration artifact or deployment guarantee exists. |
| 4 — answer shadow checks and drift | Async fresh-answer checks, tenant controller, drift replay | Not started. It needs real answer comparisons and an evaluation judge. |
| 5 — volatility and TTL | Labelled volatility corpus, classifier and staleness/hit-rate study | Not started. Existing keyword rules remain. |
| 6 — provider routing quality | Real cheap/strong answers and cost/quality frontier | Not started; requires authorized provider usage. Historical router cost ratios are illustrative. |
| 7 — scale and report | 1M-entry benchmark where feasible, measured HNSW recall/latency, full report | Not started. Existing smaller backend comparison is separate engineering evidence. |

The present data show substantial non-equivalent pair acceptance on public sources.
That directly challenges the historical smoke result; it does **not** establish the
rate of incorrect cached answers. `CACHE_MATCH_MODE=exact` remains the default.
No paid provider calls were made. Untracked `audit/` content was not modified.
