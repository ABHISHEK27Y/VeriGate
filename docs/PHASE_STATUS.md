# Research-build phase status

The two project briefs define the following sequence. A phase is only complete when
its evidence and checks exist; a working component is not a finished research claim.

| Phase | Required outcome | Current status |
|---|---|---|
| 0 — baseline and hygiene | Honest README/report, generated tables, green CI | Complete in the prior commit; current local checks remain green. |
| 1 — dataset and protocol | Public sources, answer-aware reviewed labels, grouped splits, fair baselines, CIs, filling-cache replay | **Expanded factoid proxy complete; independent answer review open.** The NQ-Open miner now requires at least 10,000 pairs and proposes typed number, attribute, entity-slot and lexical-plus-semantic hard negatives. Connected questions stay in one of five-seed grouped splits; 25% is reserved for calibration. The old replay is a small-corpus result. The optional review queue is blank and contributes no evidence. Generated-answer labels and large-cache retrieval remain. |
| 2 — learned accept policy | Trained/calibrated model, ablations, transfer and opt-in gateway use | **Expanded research rerun complete; deployment open.** The larger NQ gold-answer-match study compares static, adaptive and local-NLI learned policies over five grouped splits with separate PAWS transfer. The easy-set near-zero mismatch did not survive; all policies still accept substantial gold-answer mismatches. No trained gold model is wired into the gateway. |
| 3 — risk control | Correct bound, artifact, held-out resampling and shift study | **Larger-corpus rerun pending item 2.** The previous small-corpus exact-bound run rejected all for 1%, 2%, and 5%; it is retained separately as `gold_risk_small.csv`. No coverage or guarantee has yet been established on the expanded corpus. |
| 4 — answer shadow checks and drift | Async fresh-answer checks, tenant controller, drift replay | **Partial.** The opt-in shadow sampler records cached question and answer plus a fresh answer. A pinned local triple judge exists, but failed gold validation and produced no model-judged rows: the review queue has blank answers and shadow is off. No reviewed outcome set, drift replay or active controller exists. No real-provider shadow calls were made. See `SHADOW_REVIEW.md`. |
| 5 — volatility and TTL | Labelled volatility corpus, classifier and staleness/hit-rate study | Not started. Existing keyword rules remain. |
| 6 — provider routing quality | Real cheap/strong answers and cost/quality frontier | Not started; requires authorized provider usage. Historical router cost ratios are illustrative. |
| 7 — scale and report | 1M-entry benchmark where feasible, measured HNSW recall/latency, full report | **Partial.** The report now includes generated tables for the learned pair proxy, filling-cache replay and synthetic risk study, plus explicit threats to validity. The older 1k–10k backend comparison is separate engineering evidence; 1M-entry HNSW recall/latency and crossover remain unmeasured. |

The larger factoid corpus remains an oracle reference-answer proxy, with
lexical entity-slot categories rather than verified entity annotations.
It exposed substantial incorrect oracle-answer reuse in every tested policy.
The judge, risk, and replay numbers currently refer to the previous small
corpus. None establishes the rate of incorrect generated cached answers.
`CACHE_MATCH_MODE=exact` remains the default.
No paid provider calls were made. Untracked `audit/` content was not modified.
