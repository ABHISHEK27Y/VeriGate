# VeriGate software progress — 30 October 2026

Scope: a single-turn FastAPI gateway with an exact cache default and opt-in
semantic answer reuse. This page records implementation status; it is not an
academic results report or a production-safety claim.

| Phase | Implemented change and regression | Measured result or limitation | Next executable task |
|---|---|---|---|
| 1. Establish state | Verified PR #3 branch from `bd1e02b`; left pre-existing untracked `audit/` untouched. | Previous five CI jobs passed on that commit. | Review final PR diff and CI again. |
| 2. Scope | Kept single-turn endpoints; unsupported request fields now return 422. | No new endpoint platform. | Keep API contract stable during review. |
| 3. Cache correctness | Float32 tolerance, empty-answer exclusion, explicit `cache_bypass`, route-scoped cascade entries, and final candidate checks. See `test_answer_policy_live.py` and `test_gateway_reliability.py`. | Frozen NQ random pilot v3 accepts 10/10 exact repeats; historical v1 accepted 5/10. This is unlabelled decision behavior. | Review real-provider model provenance and route policy before enabling cascade in production. |
| 4. Failures | Successful output survives cache-write failure; lookup failures fall back after admission; Redis admission failures return 503; empty/partial/oversized responses are not cached; startup cleanup and deadlines tested. | Local fault-injection tests pass. Daily budget remains admitted misses/bypasses and is not refunded on upstream failure. | Exercise client disconnects with a real HTTP server. |
| 5. Answer policy | Long assertions abstain before NLI truncation; existing checks and thresholds retained. FLAN remains excluded. | NLI remains fallible; close-neighbor proxy finds two accepted reference mismatches. | Investigate direction and scope errors on a new development set, then test on independent reviewed data. |
| 6. Workload | Frozen NQ dev close-neighbor diagnostic with 20 directional reference matches and 20 mismatches; row-level decisions and manifests. | Answer-aware: 8 ACCEPT, 5 VERIFY, 27 REJECT; 6 accepted reference matches and 2 mismatches. Proxy only, not correctness. | Obtain an independent labelled lockbox before claiming error prevalence. |
| 7. Latency | Added bounded stage, first-byte, and completion histograms; ran live HTTP benchmark in CI against disposable Redis Stack and a delayed mock. | On CI commit `4870b1f`, exact hit 2.446 ms, semantic near-query hit 3.165 ms, and changed-number query went to provider in both modes. Eight simultaneous cold identical requests made eight provider calls. Single-request timings are descriptive only; hash embedding and mock provider were used. | Measure representative repeated traffic with real MiniLM and answer-aware policy; add single-flight only if the duplicated work is material. |
| 8. Provider path | First-token and idle-stream deadlines, bounded by total request timeout; transient first-token failure can fall back, permanent 401 does not, midstream failure never switches providers. | Fault-injection tests pass; no paid-provider call was made. | Validate a configured real provider and model ID in a separate authorized deployment. |
| 9. Security/config | Authentication now precedes body parsing on protected POST routes; production health hides configuration; `/admin/config` requires an API key; dashboard no longer embeds a demo credential. | Production startup validation and request bounds remain. | Review reverse-proxy/TLS and secrets in the actual deployment. |
| 10. Dashboard | Shows actual/intended provider and fallback on JSON calls, answer-aware decision reason, session declines and request errors; removed unsupported “wrong answers prevented” claim. | Session counts are browser-local; Prometheus has fixed-label server counters. | Inspect dashboard in a running browser with exact and semantic modes. |
| 11. Verification | Full local tests, Ruff, mypy, historical evidence validators and new pilot validator; pushed commit `4870b1f`. | 135 passed, 4 skipped locally. All five CI jobs passed on `4870b1f`, including Redis Stack tests, live HTTP benchmark, Docker build and security audit. Final documentation commit needs its own CI check. | Verify CI on the final documentation SHA. |

## Contribution ledger

| Existing technique | VeriGate implementation work | Finding supported by saved evidence |
|---|---|---|
| Exact and vector cache lookup | Tenant separation, TTL/LRU, identity recheck, opt-in semantic policy | Exact mode avoids approximate reuse; NQ random pilot has little useful cross-query overlap. |
| NLI-based answer compatibility | Concrete cached answer enters a three-action ACCEPT / VERIFY / REJECT policy; long inputs abstain | On selected close NQ reference pairs, answer-aware accepted 6 reference matches and 2 mismatches. This is not independently reviewed correctness. |
| Circuit breaker and provider failover | Owned breaker lease, first-token and idle deadlines, no mock fallback for real providers, no midstream provider mixing | Fault tests exercise first-token fallback and partial-stream terminal error. No cost or quality benefit established. |
| Redis-backed multi-tenant gateway | Admission fails closed, route partitioning, cache-write isolation, bounded request body and response | Local tests verify behavior; live production traffic and provider quality remain unmeasured. |

Historical evidence is preserved in `evaluation/runs/`; new measurements use new run IDs.
The current policy is experimental. Exact matching remains the default.

The CI live HTTP numbers above come from the `live-http-redis-benchmark` artifact
of [run 40949533050](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40949533050).
Its manifest records SHA-256 hashes for `requests.csv` and `summary.csv`. That run
used a lexical hash embedder and delayed mock provider, so it does not measure
MiniLM, an external provider, or production latency.
