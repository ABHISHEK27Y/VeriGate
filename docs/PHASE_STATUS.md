# Evidence-first phase status

This file follows the 29 October 2026 completion brief. “Implemented” means code
exists; it does not imply a validated research result or production readiness.

| Phase | State | Evidence and remaining gate |
|---|---|---|
| 0 — checkpoint and claims | Complete | README, demo page, proposal, novelty and results index corrected. At commit `a5536ef`, [CI run 40899654141](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40899654141) passed tests, Redis Stack tests, lint/typecheck, security audit, Docker build, and generated-report verification. Deploy Check was correctly skipped on the PR branch. |
| 1 — actual-answer labels | Partial | Historical 11,586 NQ rows audited: 124 of 6,000 old positives have concrete cached text absent from incoming references. Two pinned local judges now annotate the 350-row queue as `model_judged` only; [controlled validation](AUTOMATED_JUDGE_RESULTS.md) shows that FLAN fails to identify positive cases. Independent answer-quality validation is absent. |
| 2 — frozen protocol | Open | Existing grouped five-seed partitions are exploratory and their corpus was inspected during development. A fresh, independently reviewed lockbox has not been reserved or opened. |
| 3 — selective policy | Implemented, experimental | The optional [answer-aware artifact](../app/cache/artifacts/answer_policy_v1.json) routes candidates to ACCEPT, VERIFY, or REJECT. On 60 authored binary cases it accepted 16 with zero observed wrong accepts; broad answer quality is unvalidated. |
| 4 — live/replay agreement | Implemented on controlled trace | The live cache passes actual cached text to the same `AnswerPolicy.decide` used by chronological replay. A gateway/replay regression tests matching decisions. A broad Redis and real-provider trace remains. |
| 5 — immutable evidence | Partial | [Controlled run](RESULTS_ANSWER_AWARE.md) and [directional replay bundle](RESULTS_DIRECTIONAL.md) have manifests and source hashes. Latency in the controlled run excludes retrieval, embedding, network and provider time. |
| 6 — demo/report/learning | Partial | [Demo and viva guide](DEMO_AND_VIVA.md) now covers the opt-in policy and negative results. Independent transfer validation remains. |

## Capability matrix

| Capability | Classification | What can safely be said |
|---|---|---|
| Exact tenant-scoped cache, TTL/LRU, rate limit, provider failover, streaming | Implemented and tested locally | Useful gateway engineering; local mocks are not cloud quality evidence. |
| Semantic nearest-query lookup and token-diff check | Implemented but unvalidated for answer correctness | Explicit opt-in, can both falsely accept and falsely reject. |
| NLI question equivalence | Optional runtime feature | Pretrained model, question-only, no proven answer-level safety. |
| NQ strict/lenient and learned studies | Offline historical proxies | Five overlapping splits, correlated reference rows; never pool with reviewed labels. |
| Directional reference-string audit | Offline diagnostic | Detects 124 discrepancies requiring adjudication; not 124 proven wrong answers. |
| Risk selector at 1%, 2%, 5% | Failed useful-coverage experiment | Reject-all in every reported expanded-corpus split; no deployed guarantee. |
| Local FLAN-T5 judge | Failed validation | The new controlled run also found zero positive predictions; do not use as truth. |
| Local answer-aware NLI judge | Offline exploratory | 13/15 controlled binary decisions correct; two valid cases rejected and the ambiguous case received a high YES score. Not sufficient for deployment. |
| Opt-in answer-aware policy | Implemented and controlled-tested | 16/60 accepted, 0 observed incorrect accepts, 3 VERIFY decisions among 62 cases. Authored local benchmark only; exact remains default. |
| Human-reviewed answer correctness | Planned | Queue is blank; no evidence yet. |
| Production monetary savings, global novelty | Unsubstantiated | Do not claim. |

## Claim-to-evidence map

| Claim | Evidence | Boundary |
|---|---|---|
| Default is exact | [`app/config.py`](../app/config.py), exact-mode tests | Does not prove an upstream answer is true or fresh. |
| Specific-answer proxy mismatch exists | [`answer_label_audit.json`](../evaluation/results/answer_label_audit.json), local discrepancy TSV | String absence needs review; not an observed production error rate. |
| Token-diff trades coverage for lower proxy mismatch | [`gold_verifier_policies.csv`](../evaluation/results/gold_verifier_policies.csv) | Historical symmetric NQ labels and overlapping seeds. |
| Risk selection is reject-all | [`gold_risk.csv`](../evaluation/results/gold_risk.csv) | IID formal guarantee does not apply to correlated mined pairs. |
| Answer-aware policy trade-off | [immutable run](../evaluation/runs/answer_aware_20261029_v6/manifest.json), [generated report](RESULTS_ANSWER_AWARE.md) | Local authored facts, lexical hash retrieval, warm decision latency only; no production error guarantee. |
| Test suite status | [`checks.json`](../evaluation/results/checks.json), [CI run 40899654141](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40899654141) | 104 tests passed and 4 live-integration tests skipped at `a5536ef`; this verifies code checks, not answer quality. |

The old broad roadmap and [archived results](archive/RESULTS_LOG_HISTORICAL.md)
are historical context. Keep `CACHE_MATCH_MODE=exact` and the shadow sampler off by default.

## Next evidence gate

The local `data/answer_review_directional.tsv` contains 350 blank review decisions:
200 deliberately selected diagnostic cases and 150 randomly selected cases. It is
gitignored because it contains source question text. Two independent reviewers
must judge whether the **recorded cached answer** can answer the incoming question,
mark uncertainty when source context is insufficient, and resolve disagreements.
Keep both original decisions and the resolution. Until then, Phases 1–6 cannot be
reported as a completed answer-quality study or a production-ready selective
policy. The protocol for the subsequent lockbox experiment is in
[`EVIDENCE_PROTOCOL.md`](EVIDENCE_PROTOCOL.md).
