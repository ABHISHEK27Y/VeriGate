# Evidence-first phase status

This file follows the 29 October 2026 completion brief. “Implemented” means code
exists; it does not imply a validated research result or production readiness.

| Phase | State | Evidence and remaining gate |
|---|---|---|
| 0 — checkpoint and claims | In progress | README, demo page, proposal, novelty and results index corrected. Exact-revision CI and generated report drift still require final verification. |
| 1 — actual-answer labels | Partial | Historical 11,586 NQ rows audited: 124 of 6,000 old positives have concrete cached text absent from incoming references. Directional miner/loader and 350-row unreviewed local queue exist. Independent reviewer adjudication is absent. |
| 2 — frozen protocol | Open | Existing grouped five-seed partitions are exploratory and their corpus was inspected during development. A fresh, independently reviewed lockbox has not been reserved or opened. |
| 3 — selective policy | Open | The runtime has a heuristic threshold, token-diff and optional always-after-gates NLI. It has no measured ACCEPT/REJECT/VERIFY uncertainty routing. No model should be trained against unreviewed proxy labels as final truth. |
| 4 — live/replay agreement | Partial | Replay now stores a concrete simulated answer and exact mode uses an exact string key; tests cover vector ties. Live semantic policy remains query-only and does not consume the stored answer or a trained artifact. |
| 5 — immutable evidence | Partial | [One hash-vector replay bundle](RESULTS_DIRECTIONAL.md) has input/source hashes, run ID and a validator. Broad workload and provider latency profiles remain. No cloud monetary saving is measured. |
| 6 — demo/report/learning | Partial | [Demo and viva guide](DEMO_AND_VIVA.md) includes ten slides, a timed script and learning exercises. A supported final selective-policy contribution and reviewed result remain. |

## Capability matrix

| Capability | Classification | What can safely be said |
|---|---|---|
| Exact tenant-scoped cache, TTL/LRU, rate limit, provider failover, streaming | Implemented and tested locally | Useful gateway engineering; local mocks are not cloud quality evidence. |
| Semantic nearest-query lookup and token-diff check | Implemented but unvalidated for answer correctness | Explicit opt-in, can both falsely accept and falsely reject. |
| NLI question equivalence | Optional runtime feature | Pretrained model, question-only, no proven answer-level safety. |
| NQ strict/lenient and learned studies | Offline historical proxies | Five overlapping splits, correlated reference rows; never pool with reviewed labels. |
| Directional reference-string audit | Offline diagnostic | Detects 124 discrepancies requiring adjudication; not 124 proven wrong answers. |
| Risk selector at 1%, 2%, 5% | Failed useful-coverage experiment | Reject-all in every reported expanded-corpus split; no deployed guarantee. |
| Local FLAN-T5 judge | Failed validation | Do not use as truth or mix with reference labels. |
| Human-reviewed answer correctness | Planned | Queue is blank; no evidence yet. |
| Production monetary savings, global novelty | Unsubstantiated | Do not claim. |

## Claim-to-evidence map

| Claim | Evidence | Boundary |
|---|---|---|
| Default is exact | [`app/config.py`](../app/config.py), exact-mode tests | Does not prove an upstream answer is true or fresh. |
| Specific-answer proxy mismatch exists | [`answer_label_audit.json`](../evaluation/results/answer_label_audit.json), local discrepancy TSV | String absence needs review; not an observed production error rate. |
| Token-diff trades coverage for lower proxy mismatch | [`gold_verifier_policies.csv`](../evaluation/results/gold_verifier_policies.csv) | Historical symmetric NQ labels and overlapping seeds. |
| Risk selection is reject-all | [`gold_risk.csv`](../evaluation/results/gold_risk.csv) | IID formal guarantee does not apply to correlated mined pairs. |
| Test suite status | [`checks.json`](../evaluation/results/checks.json) | Counts apply to the recorded run/revision; see CI for final status. |

The old broad roadmap and [archived results](archive/RESULTS_LOG_HISTORICAL.md)
are historical context. Keep `CACHE_MATCH_MODE=exact` and the shadow sampler off by default.
