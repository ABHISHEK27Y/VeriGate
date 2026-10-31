# VeriGate software progress — 31 October 2026

## Technical verifier input comparison — 31 October 2026

The current checkout was confirmed at `69c6e683acaa94a4b02ab0eebd70168623cd2678`
on `codex/evaluation-integrity`; unrelated untracked `audit/` was left alone.
The three valid misses in technical HTTP v2 are now development cases. Their
intended candidate was retrieved with MiniLM similarities 0.947, 0.752, and
0.888. The answer assertion entered the pinned NLI model in full (49, 41, and
37 tokens); there was no truncation or structural rejection. Its entailment
scores were 0.749, 0.565, and 0.879, below the frozen 0.90 accept threshold.
The stored answers are short stipulated controls, not independently verified
complete technical answers; wording such as “setup” and “recover” may itself
be ambiguous. The exact inputs, alternative scores, and CPU timings are saved
in `evaluation/runs/technical_nli_development_20261031_v1/trace.json`.

Before running the alternative, we froze 30 new rows from 10 separate
technical families under `evaluation/runs/technical_nli_holdout_20261031_v1/`.
The workload hash is `a4772f2e8eb068de79ebbaba3a4f86963b94d6aba04938dc7749233f1fceaff2`.
Each family has one stored answer and a valid paraphrase, changed-action/entity/
permission/environment/quantity invalid neighbor, and an underspecified
question with an explicit abstention expectation. Labels are authored
stipulated procedural controls; ambiguous rows are excluded from valid/invalid
accuracy. The fixed candidate and real MiniLM similarity were identical for
both NLI inputs; the frozen policy and thresholds were unchanged. This is
pairwise fixed-candidate evaluation, not live top-k or factual validation.

| Frozen input | Valid reuse | Missed valid | Incorrect accept | Ambiguous ACCEPT / VERIFY / REJECT |
|---|---:|---:|---:|---:|
| Current answer assertion | 6/10 | 4/10 | 1/10 invalid | 4 / 5 / 1 of 10 |
| Experimental question-only NLI | 8/10 | 2/10 | 2/10 invalid | 8 / 1 / 1 of 10 |

All 10 valid candidates cleared the MiniLM retrieval threshold in each mode;
all missed valid reuse occurred after retrieval. The question-only input gained
two valid hits but also accepted a PostgreSQL restore request against a backup
answer, while both inputs accepted a Terraform apply request against a plan
answer. It accepted more underspecified questions. The experimental input is
**not enabled**; the current answer-aware policy and exact-match deployment
default remain unchanged. Saved row decisions and summary include the
denominators. On this Windows CPU run, initial RSS was 53.1 MB, after loading
and encoding with MiniLM 567.8 MB, and after NLI prewarm 794.2 MB. MiniLM load
plus encoding took 45.607 s, NLI prewarm 1.893 s with cached files; the
separate first development process took 88.440 s to prewarm NLI. Warm decision
median/p95 was 66.569/80.681 ms for current and 60.098/67.811 ms for the
question-only input. These are local process timings, not HTTP or real-provider
latency.

The non-spending real-provider preflight reports missing disposable Redis,
semantic artifact and model settings, a non-demo gateway key, and an externally
enforced spending cap/approved amount in this environment. It did not perform
an upstream probe. Existing tests cover profile-secret failure and mock routing;
the actual provider response and billed usage remain unverified. The provider
stream adapter currently does not surface usage metadata, so no real-provider
usage or cost claim is made. No paid calls were made.

## Organization workspace checkpoint (verified locally)

This branch adds a digest-only credential directory, stable organization and
subject identity, server-owned provider profiles, trusted shared technical
workspaces, private scopes, bounded top-k answer verification, a conservative
technical identity check, scoped Redis quotas, real request trace fields, and
an optional one-command mock/real-model organization demo. Legacy keys keep
their old private namespace; exact matching remains the default. Details and
startup steps are in [ORG_WORKSPACE.md](docs/ORG_WORKSPACE.md).

The frozen technical HTTP v2 run under
`evaluation/runs/technical_identity_holdout_20261031_v2/` completed 21 requests
per mode using pinned MiniLM, NLI, Redis, and a controlled answer provider.
Both unchanged and guarded modes accepted 4/7 authored valid paraphrases,
accepted 0/7 authored invalid near-matches, and made 17 provider calls. The
guard showed **no measured improvement** on this small set. Three valid
opportunities were rejected in each mode. The stipulated answers are not
independently reviewed and do not establish a production error rate. The v1
workload is development evidence after its result led to a generic action
normalization fix; its original result and runner snapshot remain intact.
The technical guard handles a bounded alias/product/action vocabulary. It can
miss unseen products and implicit relations, and can reject valid phrasing when
extraction is uncertain. It is **off by default** pending disjoint evidence of
benefit. NLI is model evidence rather than factual truth.

The two preserved runs are
[`v1/freeze.json`](evaluation/runs/technical_identity_holdout_20261031_v1/freeze.json)
and [`v2/freeze.json`](evaluation/runs/technical_identity_holdout_20261031_v2/freeze.json),
each paired with its `workload.csv`, controlled answers, per-mode `requests.csv`,
and `comparison.json`. Both used real Redis Stack, pinned MiniLM/NLI, the same
answer-policy artifact digest `f9d23650...`, and a controlled provider. The
mode toggle was `ANSWER_POLICY_TECHNICAL_GUARD=false/true`. V1 yielded 6/7
versus 5/7 valid reuse; V2 yielded 4/7 versus 4/7. Every missed valid row had
retrieved its intended stored question, so retrieval was not the cause. In V1,
the new guard rejected the MySQL backup paraphrase as an action conflict;
the generic `make a backup` normalization was then fixed, making V1 development
evidence. The Node.js deploy/release paraphrase was NLI-uncertain in both modes.
In V2, the FastAPI read/get, S3 restore/recover, and Linux install/setup
paraphrases were NLI-uncertain in both modes. There was no observed invalid
acceptance for the guard to prevent in either seven-negative set. No thresholds
were retuned on V2. Its subjects overlap V1's product domains, so it is a
limited holdout, not a fully disjoint product-domain validation.

The final local suite passed **227 tests, 5 Redis-dependent skips**. The full
suite against isolated Redis Stack passed **232 tests**. Ruff lint/format and
mypy passed. The frozen evidence, pilot, and live-run validators passed. The
existing small evaluation ran with pinned MiniLM in offline mode; its first
attempt failed when the Hugging Face client tried a network lookup. Its
historical 15-positive/15-negative results are a toy benchmark, not organization
sharing evidence. Exact-commit CI remains pending until the final push.

Actual HTTP observations are saved in
`evaluation/runs/org_http_20261031_v2/observations.json`. The seeded Alice
technical answer was reused by Carol in the same authorized workspace;
private Alice/Carol scopes and the other organization missed separately.
Forged organization fields failed validation, unauthorized workspace access
returned 403, a revoked key returned 401, and a rotated key retained Alice's
stable identity. Concurrent Alice/other-organization requests resolved distinct
mock provider profiles. No real-provider credentials or billing integration were
tested. A browser check at `/ui` displayed the backend's seeded HIT and a
misleading-question REJECT/MISS, including identity, scope, candidate rank,
decision reason, provider invocation, and stage timings. The dashboard counters
remain browser-session counters.

The isolated 5,000-entry Redis Stack measurement is saved under
`evaluation/runs/redis_capacity_20261031_v1/`: Redis used memory rose from
4,262,368 to 36,288,000 bytes (delta 32,025,632 bytes); sample serialized
payload was 1,810 bytes per entry, with a 184-byte answer and 384-dimensional
synthetic vector. At 5,000 entries, 20 warm lookup samples had median 15.365 ms
and p95 17.086 ms, with no evictions or write failures. Total Redis memory
includes keys, indexes, allocator overhead, and metadata; the payload sample
is not resident-memory usage. This synthetic measurement does not establish
production capacity or answer quality. Separate cross-process tests passed for
scoped quota enforcement and hit-recency updates. No paid provider calls were
made. Pre-existing untracked `audit/` remains untouched.

Scope: a single-turn FastAPI gateway with an exact cache default and opt-in
semantic answer reuse. This page records implementation status; it is not an
academic results report or a production-safety claim.

| Phase | Implemented change and regression | Measured result or limitation | Next executable task |
|---|---|---|---|
| 1. Establish state | Verified PR #3 branch from `bd1e02b`; left pre-existing untracked `audit/` untouched. | Previous five CI jobs passed on that commit. | Review final PR diff and CI again. |
| 2. Scope | Kept single-turn endpoints; unsupported request fields now return 422. | No new endpoint platform. | Keep API contract stable during review. |
| 3. Cache correctness | Float32 tolerance, empty-answer exclusion, explicit `cache_bypass`, route-scoped cascade entries, and final candidate checks. See `test_answer_policy_live.py` and `test_gateway_reliability.py`. | Frozen NQ random pilot v3 accepts 10/10 exact repeats; historical v1 accepted 5/10. This is unlabelled decision behavior. | Review real-provider model provenance and route policy before enabling cascade in production. |
| 4. Failures | Successful output survives cache-write failure; lookup failures fall back after admission; Redis admission failures return 503; empty/partial/oversized responses are not cached; startup cleanup and deadlines tested. | Local fault-injection tests pass. Daily budget remains admitted misses/bypasses and is not refunded on upstream failure. | Exercise client disconnects with a real HTTP server. |
| 5. Answer policy | Long assertions abstain before NLI truncation; new general answer-mention and changed-scope abstentions, with exact-repeat protection and regression tests. Artifact thresholds unchanged; FLAN excluded. | The Betty pair is a direction error under NQ references. The Eagles unscoped question has incomplete/ambiguous reference coverage. Both now VERIFY. | Test on independent, reviewed answer-quality cases before claims about general safety. |
| 6. Workload | Frozen NQ dev close-neighbor diagnostic with 20 directional reference matches and 20 mismatches; preserved v2/v4 and new v5 row-level decisions. | v5 answer-aware: 6 ACCEPT, 10 VERIFY, 24 REJECT; 6 accepted reference matches and 0 mismatches. Selected proxy only, not correctness prevalence. | Obtain an independent labelled lockbox before claiming an error rate. |
| 7. Latency | Bounded stage, first-byte, and completion histograms; live Redis Stack HTTP runs with real MiniLM and NLI; process-local JSON miss coalescing; two independent shared-Redis workers. | Three warm trials: exact hit p50 12.360 ms, valid semantic hit 11.884 ms, rejected candidate 242.726 ms with mock generation; 0 HTTP errors. Cold startup 7.535 s and first NLI hit 7.859 s separately. Three eight-request bursts made one provider call each within one worker; two-worker duplicates made two calls in all three trials. | Repeat representative traffic at larger scale and measure actual cross-worker duplication before considering distributed coalescing. |
| 8. Provider path | First-token and idle-stream deadlines; bounded real-provider smoke harness checks generation, caching, streaming, cache cleanup, and connection cleanup. | Harness passes with free mock. No paid calls: disposable Redis, real key/model, non-demo gateway key and approved external account spending cap are prerequisites. | Verify configured model ID and account cap, then execute the two-call smoke in an authorized environment. |
| 9. Security/config | Authentication now precedes body parsing on protected POST routes; production health hides configuration; `/admin/config` requires an API key; dashboard no longer embeds a demo credential. | Production startup validation and request bounds remain. | Review reverse-proxy/TLS and secrets in the actual deployment. |
| 10. Dashboard | Shows actual/intended provider and fallback on JSON calls, answer-aware decision reason, session declines and request errors; removed unsupported “wrong answers prevented” claim. | The current organization demo was inspected in a browser for a seeded HIT and mock-provider REJECT/MISS. Session counts are browser-local; Prometheus has fixed-label server counters. | Keep the fixture reset before demonstration. |
| 11. Verification | Full local tests, Redis Stack integration, Ruff, mypy, historical evidence validators and new pilot/live-run validators. | This worktree: 227 passed/5 skipped locally and 232 passed with Redis. The earlier five CI jobs on `38d021e` are historical, not this change. | Verify all five jobs on the exact final pushed SHA. |

## Contribution ledger

| Existing technique | VeriGate implementation work | Finding supported by saved evidence |
|---|---|---|
| Exact and vector cache lookup | Tenant separation, TTL/LRU, identity recheck, opt-in semantic policy | Exact mode avoids approximate reuse; NQ random pilot has little useful cross-query overlap. |
| NLI-based answer compatibility | Concrete cached answer enters a three-action ACCEPT / VERIFY / REJECT policy; long inputs, answer mention, and scope changes abstain | On selected close NQ reference pairs, runtime v4 accepted 6 reference matches and 0 mismatches. This is not independently reviewed correctness. |
| Circuit breaker and provider failover | Owned breaker lease, first-token and idle deadlines, no mock fallback for real providers, no midstream provider mixing | Fault tests exercise first-token fallback and partial-stream terminal error. No cost or quality benefit established. |
| Redis-backed multi-tenant gateway | Admission fails closed, route partitioning, cache-write isolation, bounded request body and response | Local tests verify behavior; live production traffic and provider quality remain unmeasured. |
| Process-local duplicate request suppression | Bounded same-tenant, same-prompt JSON miss coalescing with expiry and cancellation cleanup | In three real-MiniLM/Redis bursts, eight identical cold requests yielded one mock-provider invocation per burst; across two workers, three duplicate pairs each yielded two calls. |

Historical evidence is preserved in `evaluation/runs/`; new measurements use new run IDs.
The current policy is experimental. Exact matching remains the default.

The CI live HTTP numbers above come from the `live-http-redis-benchmark` artifacts
of [before run 40949533050](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40949533050)
and [after run 40951176756](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40951176756).
Each manifest hashes its `requests.csv` and `summary.csv`. The after-run rows show
one leader and seven joined requests in each mode. Both runs used a lexical hash
embedder and delayed mock provider; neither measures MiniLM, an external provider,
or production latency. JSON coalescing is local to one worker and does not suppress
duplicate work across workers.

The current [live real-path and two-worker results](docs/RESULTS_LIVE_REAL_PATH.md)
come from [CI run 40997695780](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40997695780).
Saved CSV/JSON rows and manifests are versioned under `evaluation/runs/` and
validated by `scripts/verify_live_runs.py`.
