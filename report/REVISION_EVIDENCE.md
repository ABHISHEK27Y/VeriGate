# Report revision evidence ledger

Main technical description: source commit \`37dc7a7400c1811cbf501d596d3535286ce81e17\` (recorded before editing). The saved original report is under \`report/revision_original_37dc7a7/\`. Report files were the only source files edited. Concurrent implementation changes are provisional until final reconciliation.

| Significant report claim | Primary code or immutable artifact | Boundary |
|---|---|---|
| Exact match is the general default; semantic and answer policy are opt-in | \`app/config.py\` defaults; \`app/cache/semantic_cache.py\` lookup branches | Configuration can change per deployment. |
| Principal, workspace, private scope, provider profile, HMAC scope identity | \`app/organization.py\` principal and scope methods; \`app/main.py\` principal and registry selection; \`tests/test_organization_scopes.py\` | Classification and configuration errors remain possible. |
| Rate check precedes lookup; miss/bypass budget follows lookup | \`app/main.py\` chat and chat_stream handlers | The daily count is not a monetary cap. |
| MiniLM embeddings, in-process or RedisSearch top-k, exact fast path, candidate recheck | \`app/embeddings.py\`, \`app/cache/semantic_cache.py\`, \`app/cache/redisearch_store.py\` | In-process scan is not sub-linear; RedisSearch is configuration dependent. |
| Answer-policy candidate actions and stored-answer assertion | \`app/cache/answer_policy.py\`, pinned \`app/cache/artifacts/answer_policy_v1.json\` | NLI is a suitability signal, not factual verification. |
| Normal provider completion and scoped response storage | \`app/main.py\`, \`app/providers/registry.py\`, \`tests/test_provider_completion.py\` | No paid-provider smoke is recorded. |
| Supported single-turn API and input bounds | \`app/schemas.py\`, \`app/limits.py\` | Not a universal OpenAI proxy. |
| Archived 303 passed, 7 skipped | \`evaluation/results/checks.json\` and \`report/generated/checks.tex\` | Historical local result; no exact-revision final suite claimed. |
| Fixed-candidate 60 binary + 2 ambiguous controls | \`evaluation/runs/answer_aware_20261029_v6/manifest.json\`, \`docs/RESULTS_ANSWER_AWARE.md\` | Authored development set, hash embeddings, warm decision timing. |
| Fixed-candidate applicability 32 cases and bidirectional 30 cases | \`evaluation/runs/technical_applicability_lockbox_20261101_v1/results/summary.json\`; \`evaluation/runs/technical_bidirectional_lockbox_20261101_v1/results_timed/summary.json\` | Stipulated task labels; not real traffic. |
| Earlier live 25-probe result, 4/15 valid reuse | \`evaluation/runs/technical_applicability_live_20261101_v1/results_complete/summary.json\`, \`trace_analysis.json\`, \`manifest.json\` | Controlled provider; archived summary misnames 21 assessed misses as verification abstentions. Trace analysis gives 10 request abstentions. |
| Fresh 25-probe combined-guard result, 6/15 vs 8/15 valid reuse | \`evaluation/runs/technical_combined_fresh_20261101_v1/freeze.json\`, \`results_forward_verified/manifest.json\`, \`summary.json\`, \`results_reverse/summary.json\` | Same authored cases in two orders; promotion gate of +3 valid hits was not met. |
| Prewarm timing and process memory | \`evaluation/runs/prewarm_semantic_8d79c81_v1/manifest.json\`, \`requests.csv\`, \`summary.csv\`; \`evaluation/runs/technical_combined_fresh_20261101_v1/nli_memory.json\` | Selected mock-provider and one-process observations. |
| Published methods | GPTCache [ACL Anthology](https://aclanthology.org/2023.nlposs-1.24/), [project examples](https://github.com/zilliztech/GPTCache/blob/main/examples/README.md); [vCache](https://arxiv.org/abs/2502.03771); [Krites](https://arxiv.org/abs/2602.13165) | Literature, not reproduced VeriGate results. |

The generated proxy tables in Appendix A remain unchanged and are traceable to \`evaluation/results/\` via \`scripts/export_report_tables.py\`. The report does not use the unverified dashboard screenshots.

## Expanded report evidence (1 November 2026)

| Report result or design claim | Saved source | Configuration and boundary |
|---|---|---|
| Selected 13-request HTTP release probe: seeded Carol HIT at rank 1 and 13.64 ms; a later valid paraphrase missed; cross-organization and private paths stayed separate | `evaluation/runs/release_http_20261101_v1/README.md`, request observations and manifest | Image from source commit `37dc7a7`; real Redis Stack, pinned MiniLM and NLI, two mock profiles; selected local smoke, no paid call |
| 1,000-request song-writer stress: exact 1,000 calls; static 198 calls, 712 reference-matching and 90 suspected wrong HITs; answer-aware 264 calls, 682 reference-matching and 54 suspected wrong HITs | `evaluation/runs/nq_song_stress_20261030_v3/REPORT.md`, freeze, manifests and rows | 200 NQ-Open train families, five requests each; controlled fixed-answer provider, Redis Stack, pinned models; sequential local run; suspected wrong means short-reference mismatch, not adjudicated error |
| Warm local HTTP p50/p95 of 35.193/51.006 ms exact, 63.894/142.934 ms static and 211.609/364.226 ms answer-aware | Same 1,000-request stress report and timing rows | 999 post-first requests per policy at sufficient capacity; timings include controlled misses and vary by HIT/MISS mix |
| Earlier live top-k suitable candidates retrieved in all 15 valid cases but only 4/15 accepted; 11 missed from five VERIFY and six REJECT candidate decisions | `evaluation/runs/technical_applicability_live_20261101_v1/results_complete/trace_analysis.json` and manifest | Authored 25-probe controlled-provider run; not independent traffic |
| Fresh combined-guard valid reuse 6/15 baseline versus 8/15 combined, short of predeclared +3 promotion gate | `evaluation/runs/technical_combined_fresh_20261101_v1/freeze.json`, forward and reverse summaries | Five new authored families; same tasks in two orderings; experimental guard, not promoted improvement |
| 596-token assertion against 512-token verifier window abstained; 24-case freshness set bypassed 12/12 volatile and 6/12 stable questions | Timed bidirectional lockbox; `evaluation/runs/freshness_dev_20261030_v3/summary.json` | Authored tasks; correct safety boundary can still lose useful reuse |
| Redis shortlist validation sequential median 3.357 ms, pipelined median 0.896 ms in 80 rounds; NLI prewarm raised one process RSS by about 681 MB | `evaluation/runs/technical_combined_fresh_20261101_v1/redis_shortlist_benchmark.json` and `nli_memory.json` | Local stage measurements, not whole-request production acceleration or multiworker memory bound |

The corrected standalone vector diagrams are editable in `report/figures/*.tex` and compiled, without source rewriting, by `report/figures/build_diagrams.py`. `report/DIAGRAM_EVIDENCE.md` maps each final figure to code, configuration, omissions, and placement. The diagram correction uses source checkpoint `1cdb80a78ebb8bd00a53cea42aa080a523af950e`; the earlier evaluation results retain their own recorded source and run boundaries. No dashboard screenshots or paid-provider results were invented.

## Product framing and diagram correction pass

The report now explains multiple isolated organizations, authorized workspace sharing across employees, private response restrictions, automatic default scope resolution, and separate gateway/provider credentials. These descriptions remain tied to the recorded source checkpoint, not concurrent edits. Chapter 6 adds analytical cost and mean-latency break-even conditions; these equations and the 100-request example are illustrations, not measured savings. Corrected client use cases, authorization arrows, provider connectivity, and candidate model inputs. The subsequent expansion adds detailed requirements, design diagrams, implementation walkthroughs, and evidence-backed testing; its final page count and render checks are recorded in the handoff.
