# Research-build phase status

The two project briefs define the following sequence. A phase is only complete when
its evidence and checks exist; a working component is not a finished research claim.

| Phase | Required outcome | Current status |
|---|---|---|
| 0 — baseline and hygiene | Honest README/report, generated tables, green CI | Complete in the prior commit; current local checks remain green. |
| 1 — dataset and protocol | Public sources, answer-aware reviewed labels, grouped splits, fair baselines, CIs, filling-cache replay | **Expanded factoid proxy and two label rules complete; independent answer review open.** The NQ-Open miner has 11,586 pairs and proposes number, attribute, entity-slot and lexical-plus-semantic negatives. Connected questions stay in grouped splits; 25% is reserved for calibration. The strict alias rule has 6,000 positives; the broader lenient rule has 6,535. They are evaluated separately and neither is human answer review. The old replay is a small-corpus result. The optional review queue is blank and contributes no evidence. Generated-answer labels and large-cache retrieval remain. |
| 2 — learned accept policy | Trained/calibrated model, ablations, transfer and opt-in gateway use | **Lowercase-safe verifier and five-seed strict/lenient rerun complete; deployment open.** `adaptive_token_diff` checks answer type and changed role/content tokens without capitalization. The old capitalization check remains an ablation. Across the strict corpus, token-diff coverage averaged 6.4% and mismatch among served 3.6%; with lenient labels, coverage was 6.4% and mismatch 2.3%. These are far below the capitalization baseline's 68.8% coverage, so the lower observed mismatch carries a severe coverage loss. The hand-authored smoke fixture now accepts 0 of 30 pairs with Tier-1, an additional sign this rule is overly restrictive for paraphrases. Group-bootstrap CIs and all policy comparisons are in `gold_verifier_policies.csv`; the smoke result is in `metrics.csv`. The 100-per-policy false-accept audit remains strict-label evidence. The requested trained cross-encoder is item 3, still open. No trained gold model is wired into the gateway. |
| 3 — risk control | Correct bound, artifact, held-out resampling and shift study | **Expanded-corpus item 2 complete as a negative result; deployment open.** The exact finite-grid bound selected reject-all at 1%, 2%, and 5% in all five grouped splits, giving zero held-out coverage. The best nonempty candidate had a 7.9% upper bound. Candidate diagnostics, selected outcomes, and zero-error sample minima are in `gold_risk_candidates.csv`, `gold_risk.csv`, and `gold_risk_min_samples.csv`. Correlated oracle labels prevent a formal production guarantee; a reviewed generated-answer risk study and a usable deployable artifact remain open. |
| 4 — answer shadow checks and drift | Async fresh-answer checks, tenant controller, drift replay | **Partial.** The opt-in shadow sampler records cached question and answer plus a fresh answer. A pinned local triple judge exists, but failed gold validation and produced no model-judged rows: the review queue has blank answers and shadow is off. No reviewed outcome set, drift replay or active controller exists. No real-provider shadow calls were made. See `SHADOW_REVIEW.md`. |
| 5 — volatility and TTL | Labelled volatility corpus, classifier and staleness/hit-rate study | Not started. Existing keyword rules remain. |
| 6 — provider routing quality | Real cheap/strong answers and cost/quality frontier | Not started; requires authorized provider usage. Historical router cost ratios are illustrative. |
| 7 — scale and report | 1M-entry benchmark where feasible, measured HNSW recall/latency, full report | **Partial.** The report now includes generated tables for the learned pair proxy, filling-cache replay and synthetic risk study, plus explicit threats to validity. The older 1k–10k backend comparison is separate engineering evidence; 1M-entry HNSW recall/latency and crossover remain unmeasured. |

The larger factoid corpus remains an oracle reference-answer proxy, with
lexical entity-slot categories rather than verified entity annotations.
It exposed substantial reference-answer alias mismatch in every tested policy.
The false-accept audit highlights possible alias-label noise: some answer strings
differ by granularity or formatting and require manual review before claiming
they are truly wrong answers.
The lenient rule is itself noisy: shared years or name parts can belong to
different facts. Strict and lenient outcomes must remain separate.
The judge and replay numbers currently refer to the previous small corpus;
risk was rerun on the expanded corpus. None establishes the rate of incorrect
generated cached answers.
`CACHE_MATCH_MODE=exact` remains the default.
No paid provider calls were made. Untracked `audit/` content was not modified.
