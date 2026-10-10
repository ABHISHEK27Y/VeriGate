# VeriGate Production-Readiness Audit Report

## Remediation update — 10 October 2026

The sections after this update preserve the original audit evidence. Their original open
counts are historical. The implementation findings have now been addressed locally; release
approval still requires fresh Linux/Redis Stack/container CI for the final revision.

| Finding | Remediation |
|---|---|
| M01 semantic false hits | Exact UTF-8 prompt matching is now the default, using an authoritative Redis hash key. Semantic reuse is opt-in and documented as probabilistic. Role-reversal regression added. |
| M02 incompatible cache namespaces | Versioned SHA-256 namespaces cover model/revision/dimension, provider identity/model, cascade, policy and deployment epoch. RediSearch validates existing vector type/dimension/distance. Finite TTL retires new namespaces. |
| M03 misleading spend cap | Renamed/documented as daily admitted miss/bypass requests. It does not claim to limit retries, tokens or money; provider-side financial controls remain required. |
| M04 resource bounds | Actual body bytes, request-body deadline, whole-response concurrency, entry bytes/count/TTL, local tenant indexes and cancellation-safe inference admission are bounded. Production requires finite Redis maxmemory. |
| M05 observability | Bearer-token secret mounted for Prometheus; supported multiprocess collection tested across two independent worker processes; streaming completion/error metrics added. |
| M06 mutable settings | Validated frozen app snapshots and request-local context; independent app authentication and mutation rejection tested. |
| M07 breaker races | Generation checks and probe ownership prevent late success or expired probes from resetting newer state. Permanent HTTP failures do not trip transient-failure counters; namespace isolates provider configurations. |
| N01 documentation | Current behavior documented in PRODUCTION_CONFIGURATION.md; unsafe historical claims corrected or explicitly identified as historical experiment results. |
| N02 reproducibility | CPU-only transitive hash locks, model commit revisions and container image digests pinned. CI/container consume locks. The clean lock exposed a pytest advisory; upgraded pytest and its asyncio plugin. |
| N03 tenant bookkeeping | Fixed lock stripes, bounded local tenant indexes, expiring revision/membership metadata. Pre-v3 data from old deployments requires deliberate legacy cleanup after rollback retention. |
| N04 Redis typing | Removed invalid runtime Redis union; typed client boundary helpers contain redis-py's mixed sync/async annotations. |
| N05 readiness | Separate /live and /ready; readiness verifies Redis and semantic RediSearch schema. Response explicitly identifies provider health as configuration-only. |
| N06 dashboard errors | All non-2xx responses handled; failed clears no longer claim success; displayed request history bounded. |

Additional efficiency fixes: batched Redis index reads, bounded victim reads during writes,
reused provider HTTP pools and app-owned binary Redis pools, Redis server time for live Lua
rate limiting, and exact mode avoids embedding inference entirely.

Validation evidence is under `audit/evidence/remediation/` (local artifacts, not secrets or
runtime environments). A clean Python 3.11 environment installed the complete hash-verified
CPU lock. The updated toolchain passed **50 tests**; live Redis tests are separately gated
and require a disposable server. Cross-process Prometheus aggregation passed. Semantic
accuracy evaluation completed with the pinned cached models: Tier-1 5/15 positive hits and
0/15 observed negative hits; NLI 3/15 and 0/15. This small dataset is not a correctness proof.
The release wheel built successfully. Final local lint and format checks pass; MyPy passes all 28 modules. The
final dependency scan covers 99 installed third-party packages with zero known
advisories. Live Redis gates are present as four tests, skipped locally because no
server is available. GitHub CI results will be recorded when available.

The dependency scanner cannot find the local `torch +cpu` version on PyPI. The checked-in
scanner maps only that suffix to its identical upstream release number for advisory lookup;
the installed CPU artifact is separately pinned and hash-verified. All installed third-party
packages are included; the local VeriGate project itself is reviewed as source.

The missing VeriGate Git metadata was restored from its verified GitHub origin on
10 October, preserving all working source files and keeping the parent Drecovery
repository untouched.

Final continuation checks: lint and formatting pass, MyPy passes 28 source modules,
and the final vulnerability scan covers **99 packages with zero known advisories**.
The final suite reports **50 passed, 4 live Redis tests skipped**, with the previously
recorded 81% coverage. Package inspection confirms the wheel includes the dashboard.

Git metadata is restored for VeriGate at the original audited HEAD; remediation is
committed on `codex/production-audit-remediation`. The parent Drecovery repository was
not modified. Automatic approval review rejected uploading this branch to the public
GitHub repository because the user has not explicitly authorized source upload to that
destination. No push or pull request was created. Fresh CI is pending that authorization.

**Remaining release gates:** B01 fresh GitHub checks and B02 current Docker/live Redis Stack
checks. The local Docker Linux engine is absent even outside the sandbox and after hidden
Desktop startup; WSL Ubuntu is available but has no Redis server. No production deployment
or paid provider calls have been performed.

---

## Executive Summary

- **Overall status: FAIL.** Do not deploy the audited checkout as production-ready.
- **Open blocking issues: 2** (B01–B02, validation/release gates).
- **Open major issues: 7** (M01–M07).
- **Open minor issues: 6** (N01–N06).
- Numerous confirmed defects were repaired locally; the fixed findings below are not counted again as open findings.
- Latest complete regression run: **39 passed**, **81% statement coverage**; final verification and artifact results are recorded below and in `audit/evidence/`.
- Dependency scan: initially **24 advisory records / 14 distinct package-advisory pairs across 3 packages**; updated requirements resolve **59 packages with zero reported advisories**. This is the scanner's result, not a guarantee of no vulnerabilities.

Scope: working tree at `D:\miniProject\verigate`, branch `main`, HEAD `630269b771ede17afdaf1d3a1e56aa418ad7a8fa`. Eighteen paths were already modified at takeover, including core app files and benchmark outputs. Those changes were preserved and built upon; do not attribute the entire Git diff to this audit. A pre-edit snapshot is retained in `audit/evidence/pre-audit-source.zip`.

Work began **9 October 2026, 19:45 IST**, paused after an approval-service usage limit, and resumed **10 October 2026, 09:53 IST**. More than 30 minutes of active audit work was performed across the sessions; the overnight pause is not counted. No commits, pushes, deployment, or paid upstream calls were made. Local demos used mock providers and cached ML models.

This is a scoped adversarial audit, not a proof that every possible defect has been found. Evidence distinguishes observed failures, source-review risks, local fixes, and unverified deployment behavior.

## CI/CD Status

Main status refreshed on 10 October 2026; latest inspected run: [GitHub Actions run 37941194818](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/37941194818), HEAD `630269b`.

- [ ] Lint & Typecheck passing on GitHub — **FAILED at Install dependencies**, lint/typecheck steps skipped.
- [ ] Tests with Redis Stack passing on GitHub — **FAILED at Install dependencies**, tests skipped.
- [ ] Security Audit passing on GitHub — **FAILED at Install dependencies**, audit skipped.
- [x] Docker build passing — **PASS on that committed GitHub run**, including health smoke test; **current local changes remain unbuilt in Docker**.
- [ ] Standard Tests job — **FAILED at Install dependencies**.
- [ ] Deploy Check — **SKIPPED** due to failed dependencies.

Evidence: `github-runs.json`, `github-runs-final.json`, `github-jobs.json`. `gh run list --limit 10` could not run because `gh` is absent. Equivalent public REST endpoints supplied run/job status. Downloading the failed job log returned **403, Must have admin rights to Repository**; therefore the exact installer log is unavailable. The malformed TOML was independently reproduced with Python's TOML parser and explains a local packaging failure, but is not presented as a verified excerpt from GitHub's inaccessible log.

CI edits: valid TOML, repo-wide lint scope, a Python Redis health probe instead of assuming `redis-cli` is installed on the runner, and explicit opt-in to destructive reset of the disposable Redis test database. No new remote run was triggered.

## Critical Findings (Blocking)

| ID / Issue | File:Line | Severity | Fix Required |
|---|---|---|---|
| B01: Required main-branch gates are red and local changes have no fresh CI result | `.github/workflows/ci.yml:9` | Blocking | Review/commit the patch, run all jobs on Python 3.11, inspect actual logs, and require a green Deploy Check before release. |
| B02: Production Redis Stack and current container behavior remain unverified | `app/cache/redisearch_store.py:52`; `Dockerfile:3` | Blocking | Start a disposable Redis Stack; run the complete suite, independent workers, TTL/clear/eviction and Lua tests; build and smoke-test the changed Docker image. Local Docker client exists but the Linux engine pipe is absent, including after attempting background startup. |

### Confirmed defects repaired locally

| Finding | Original evidence / impact | Fix and verification |
|---|---|---|
| Invalid `pyproject.toml` inline table | `tomllib` throws at original line 47; MyPy printed a TOML error while later reporting success, so the baseline success was misleading | Converted to a TOML subtable. Current parser/typecheck/package evidence is separate. |
| Every real upstream request constructed an invalid HTTPX timeout | Direct reproduction raised `ValueError` before sending a request | All four timeout categories now have defaults; MockTransport test verifies actual request/auth/SSE parsing. |
| Silent mock failover concealed real provider outages | A real-provider error could return and cache a mock answer as success | Mock is used only when explicitly selected. Missing real credentials reject startup; upstream outages return generic 502, not private exception details. |
| Expired, cleared, and cross-worker cache state was stale | Saved original code: `EXPIRED HIT`, `CLEARED_OTHER_WORKER HIT`, `INSERT_OTHER_WORKER MISS` | Redis revisions invalidate local indexes; immutable build snapshots prevent half-built parallel arrays; candidate existence is checked before serving. Regression covers TTL, other-worker clear and writes. |
| Cache eviction/storage metadata was not one transaction; eviction was FIFO despite LRU naming | Multi-command writes could interleave; reads never refreshed LRU | Shared WATCH transactions include hash, membership, revision, TTL, eviction; read hits refresh recency. 50 writes across five cache instances leave exactly 3 entries with capacity 3; LRU order tested. |
| RediSearch ignored cache TTL, size cap, and tenant clear; exception paths leaked connections | Original `add()` only wrote a hash; clear read unrelated inproc metadata | Separate `cache:rs:` namespace, shared transactional metadata/TTL/eviction, clear support, tenant TAG escaping, connection cleanup in `finally`, bounded timeouts/pools. **Source and shared-storage tests only; live RediSearch validation is B02.** |
| Module-global Redis, rate limiter, default registry and gateway embedding model | Cross-lifespan client ownership and worker-local fake-Redis divergence | Gateway resources now owned by `app.state`; handlers use `request.app.state`. Registry containers are tuples/read-only mappings. Separate-lifespan resource identity regression passes. |
| Synchronous embedding/NLI work blocked async request handlers | Original cache called model inference directly | Thread offloading plus per-model locks; NLI lazily loaded per gateway policy. Availability failure rejects reuse instead of silently disabling NLI. Model startup errors now fail startup instead of switching vector spaces to hash. |
| API credentials appeared in Redis keys, partial credentials in logs, complete Redis URL in logs | Original rate/budget key naming and connection log | HMAC-SHA256 tenant/storage IDs with configurable secret salt, no raw Redis URL log, request ID response header, opaque tenant logs. Regression scans created keys for the supplied credential. |
| Weak defaults and wildcard credentialed CORS | No production configuration guard | Explicit `ENVIRONMENT=production` checks Redis, non-demo keys, private metrics token, secret salt, explicit origins and real provider. Same-origin CORS by default. **Deployment must actually set production mode.** |
| Circuit breaker retried all-open providers and ignored failures after first chunk | Original `healthy or order`; success recorded before consuming stream | No all-open retry, shared leased half-open probe, stream-completion success, midstream failure recording. Regression covers all-open rejection, one of 30 probe contenders, midstream failure. Remaining race limitations: M07. |
| Budget denied requests continued incrementing; counter and expiry were separate | Original `INCR` then `EXPIRE` | WATCH-based cap reservation and expiry are atomic, denied requests do not increase usage. 50 concurrent admissions with budget 5 admit exactly 5. Cache hits remain free. |
| Conversation history silently discarded | Different system/history inputs produced identical cache text | Stateless endpoint now accepts a prompt or **one user message**; unsupported history/system roles and ambiguous inputs return 422. This is an intentional compatibility change. |
| SSE newlines could change event framing | Raw answer/chunks interpolated into `data:` | JSON-string payloads preserve newlines; test covers MISS and HIT. SSE clients must decode JSON strings. Upstream preflight errors return 502; later errors emit an error event without caching a partial answer. |
| Unbounded answer assembly and missing upstream completion validation | Stream chunks accumulated without a bound; EOF could be accepted as completion | Configurable response-character cap, provider deadlines, `[DONE]` requirement on OpenAI-compatible stream. Some disconnect/truncation cases still need broader tests (coverage section). |
| Verifier missed apostrophe negations and initial proper nouns | Original accepted `isn't working`/`is working` and `Austria capital`/`Australia capital` | Normalize apostrophes before negation checks; inspect first-token proper nouns. Both reproduced failures are regression tests. This remains a heuristic, not NER (M01). |
| Clock queries and plural price/stock queries missed volatility bypass | Keyword list lacked those variants | Added clock phrases and plural terms; regression preserves stable “time complexity” behavior. Rule coverage remains limited. |
| Vulnerable dependency constraints | Baseline resolver selected old Starlette and Transformers; details in JSON | Updated FastAPI 0.143.0, Starlette 1.7.0, sentence-transformers 6.1.0, Transformers 5.19.0 in both manifests; zero advisories in the subsequent resolved scan. |
| Benchmarks misstated what they timed; destructive backend benchmark | “HIT” query was absent from populated cache; KNN included embedding; NLI reused memoized pairs; backend compare used nested `asyncio.run()` and `FLUSHALL` | HIT is now asserted and warmed, KNN uses precomputed vector, NLI cache cleared for inference timing, backend calls awaited, global flush removed, unique benchmark tenancy. |
| Demo/lifespan and routing inconsistency | semantic demo set backend after settings import; RediSearch check omitted TestClient context; cascade used 0.5 instead of configured 0.35 | Fixed import order/context managers; deterministic rate-limit demo refill; cascade uses configured default. |
| Exposed local infrastructure | Redis/RedisInsight and anonymous-admin Grafana bound all host interfaces | Bound infrastructure ports to localhost; Grafana requires login and an explicit password. Prometheus auth still needs wiring (M05). |
| Missing packaged dashboard declaration | Installed wheel could omit static HTML | Declared `app/static/*.html` package data and inspected the generated wheel. |

## Architecture Findings

| ID / Component | Issue | Risk | Recommendation |
|---|---|---|---|
| M01 — semantic correctness | Capitalization and number/negation **sets** cannot establish equivalence. The original and remaining heuristic accepts reordered roles such as “move 5 from A to B” vs “move 5 from B to A”; lowercase entity changes and numeric association are not reliably covered. | Wrong answers within an authorized tenant; a small benchmark with zero observed false hits is not a safety guarantee. | Evaluate domain-specific hard negatives, use structured slots and real entity recognition, and use exact-match/bypass policy for correctness-critical operations. Validate NLI rather than claiming it guarantees correctness. |
| M02 — cache schema/model identity | Tenant keys and RediSearch index are not fingerprinted by embedding model/revision, dimension, upstream model, prompt policy or deployment version. `ensure_index` does not validate an existing schema's dimensions. | Reconfiguration can reuse obsolete answers or cause vector errors. New salted tenant IDs and `verigate_idx_v2` also leave pre-existing data orphaned. | Version cache namespaces and index schema; plan a bounded, explicit migration/retention policy. Do not mix deployments with different vector models in one namespace. |
| M03 — economic budget | Reservation counts one gateway cache-miss admission, not actual billable provider attempts/tokens. Cascade/failover can attempt more than one provider; failed admissions retain their reservation. | “Daily spend cap” and “provider call count” comments overstate the guarantee. | Name/document this as an admission limit, or separately meter/reserve every upstream attempt and token spend with reconciliation. |
| M04 — resource and ingress policy | Pydantic limits prompt characters after request-body parsing. No raw body-byte limit, global concurrency bound, tenant/global memory-byte cap, or cancellation-safe inference queue. Zero cache TTL/unlimited size remain configurable. | Large JSON bodies and sustained authorized requests can exhaust memory/CPU despite token buckets. | Enforce ingress byte limits, bounded concurrency, positive production retention and total resource budgets; measure under sustained load. |
| M05 — observability | Prometheus configuration sends no `X-Metrics-Token`; `/metrics` requires it. Prometheus counters use process globals without multiprocess aggregation. Streaming request/latency metrics and error coverage differ from JSON endpoint. | Scrapes fail with 401; multi-worker telemetry is incomplete; failures can be undercounted. | Wire a secret-backed scrape header, add multiprocess/exporter design, and unify request outcomes/latency/error metrics. |
| M06 — configuration isolation | `settings` remains a module-level mutable `Settings` object. Models/registries snapshot some fields while request-time policy and rate/budget code read others dynamically. | Concurrent apps or runtime config mutation can mix incompatible settings; per-app resources alone do not solve config ownership. | Freeze startup configuration and inject one validated settings snapshot into each app/resource. Runtime changes should create a new versioned deployment. |
| M07 — breaker semantics | All exceptions count alike; delayed success can reset newer failures/open state. Half-open lease has no ownership/generation token, and a long or stalled probe can outlive its lease. | 4xx behavior and concurrency can produce avoidable outages or duplicate probes. | Classify transient vs permanent/rate-limit errors, make transitions atomic with generation/lease tokens, and test overlapping timeout/success/failure schedules across workers. |

Application resources now include `app.state.model`, `index`, `providers`, `redis`, `cache`, `verifier`, and `rate_limiter` (compatibility aliases `semantic_cache` and `provider_registry` remain). Redis dependency `get_redis(request)` returns app state. No `global` statement remains in app code. Bounded `default_embedder()` / `default_verifier()` caches are convenience singletons for standalone evaluations; the gateway explicitly supplies its own instances. Module-level Prometheus collectors, logging setup, settings, compiled patterns and constant sets remain; they are not equivalent risks and should not be conflated with cross-loop client ownership.

## Security Findings

| Issue | CWE | Severity / State | Fix |
|---|---|---|---|
| Vulnerable resolved dependencies | CWE-1104 / package-specific weaknesses | High, local remediation scanned clean | Updated constraints; retain CI audit of the actual target-platform environment. |
| Credentials in storage keys/logs | CWE-532, CWE-312 | High, fixed locally | Opaque keyed hashes; no partial credential logs or Redis URL logging. Production salt must be random and stable. |
| Silent wrong-answer reuse / dropped conversation context | CWE-841 (business logic), CWE-20 | High, repaired context handling; residual M01 | Reject unsupported history; strengthen domain correctness policy. |
| Public anonymous-admin Grafana and open local Redis ports | CWE-306, CWE-668 | High, fixed in compose | Loopback ports, authenticated Grafana. Public gateway exposure still requires TLS/ingress controls. |
| Default demo credentials / wildcard CORS | CWE-1188, CWE-942 | High if misdeployed; production guard added | Set `ENVIRONMENT=production`; provision secrets and allowed origins explicitly. Render blueprint remains a public **mock demo**, not a production deployment. |
| Raw SSE interpolation | CWE-74 | Medium, fixed | JSON-string framing and explicit error event. |
| Unbounded request-body / concurrent-work pressure | CWE-400 | Major, M04 open | Ingress size and concurrency limits. |
| Secret hygiene | CWE-798 | No token-pattern finding in tracked files; limited scan | `.env` is untracked, ignored, and absent from `git log --all -- .env`. Pattern scan does not prove no secret ever appeared in another file/history/object. |

`/metrics` correctly returns 401 without a token. It deliberately accepts **X-Metrics-Token**, not the checklist's **X-API-Key**; ordinary tenant credentials are not monitoring credentials. CORS absence is now same-origin-only. Docker runs as non-root `appuser`. Full TLS, Redis authentication/network policy, secret rotation and platform permissions are deployment responsibilities not verified by a local TestClient.

Primary advisory context: [Starlette form parser DoS](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq), [Transformers reviewed RCE advisory](https://github.com/advisories/GHSA-29pf-2h5f-8g72). These describe affected library behavior; this audit did not demonstrate exploitation of every advisory through VeriGate's endpoints. Scanner JSON retains exact package/version/advisory data and duplicate records.

## Novel Contributions: Verified Behavior and Specification Differences

| Component | Result |
|---|---|
| Adaptive threshold | Per-query features and neighbourhood density change the threshold; bounds are **0.70–0.98**, not requested 0.65–0.95. Volatility is handled by bypass, not a threshold bump. No evidence justifies silently changing calibration to match the checklist. |
| Tier-1 verifier | Number, negation, and capitalized-entity mismatches reject; returns `(bool, reason)` via `verify_equivalent`. There is no `verify_tier1` function, real NER model or overlap-at-0.5 calculation. Entity sets are compared for equality. |
| Tier-2 verifier | Lazy cross-encoder, bidirectional entailment, bounded pair memoization. App inference runs off-loop; unknown/unavailable model/label configuration rejects reuse. Model label IDs are read from configuration instead of assuming position 1. |
| Volatility | Keywords bypass lookup and storage. Status is **BYPASS**, not MISS. Stable controls pass; keyword rules still have false positives/negatives outside the small dataset. |
| Tenant isolation | Keys use opaque tenant hashes inside `cache:*:<tenant>` and `cache:rs:*:<tenant>` rather than literal `tenant:{hash}:` prefixes. Existing end-to-end isolation test passes on fake Redis; live TAG filtering remains B02. |

## Local Verification and Evidence

| Check | Result / caveat | Evidence |
|---|---|---|
| Initial Ruff | PASS on pre-audit working tree | Initial tool output; not a statement about committed CI |
| Original tests | 19/19 PASS using original test behavior with mock/hash/fake Redis after minimal import/TOML repairs | `tests-baseline-executed.log` |
| Pre-audit reproductions | Stale TTL/clear, invisible writes, missed negation/entities, context collision reproduced from saved source | `baseline-probes.log`, `pre-audit-source.zip` |
| Final lint | PASS | `lint-final.log` |
| Final formatter | PASS | `format-final.log` |
| Final MyPy | PASS, 26 app modules, valid configuration | `mypy-final.log` |
| Final tests / coverage | 39 PASS, 81% | `tests-final.log`, `coverage-final.json` |
| Package wheel | PASS after clearing audit-generated stale build output; dashboard included | `package-build-final.log`, `wheel-inspection.log` |
| Dependency audit | 59 resolved dependencies, zero reported advisories | `dependency-audit-after.json` / `.log` |
| Docker | Current local build blocked: Docker Linux engine pipe unavailable | `docker-version.log`, `docker-build.log` |
| GitHub failed logs | Status API available; download denied 403; gh CLI unavailable | `github-jobs.json`; audit narrative above |
| Secret-pattern scan | No matched tracked token patterns; `.env` not tracked/history-listed | `secret-scan.json` |

The host uses Python **3.13.2**; CI targets **3.11**. A workspace-local package overlay (`audit/tmp/runtime`) tested patched FastAPI/Starlette and ML packages without changing global Python. It reuses some host dependencies and is **not a clean locked production environment**. Native asyncio initially hung in Windows sandbox socket-pair creation; the traceback is in `tests-controlled.log`. Tests/evaluations then ran with authorized loopback access outside that sandbox. Initial coverage command also exposed that pytest-cov was not installed; it was installed locally for the measurements.

A temporary approval-review usage limit blocked one final test attempt; it was resumed on 10 October. No blocked attempt is reported as a successful run. The packaged wheel contains the dashboard asset. Initial package builds failed while cleaning stale Windows build output; the clean rebuild succeeded. The pinned development-tool versions have not all been recreated in a clean Python 3.11 environment; B01 covers that release check.

The prompt's manual snippets do not match this implementation: `TestClient.post()` returns a response, not a coroutine to gather; `SemanticCache(max_size=3)`, `.set()` and `verify_tier1()` do not exist; arbitrary API keys `k`/`burst` fail authentication. Equivalent working scenarios use `httpx.AsyncClient` with ASGITransport on the lifespan event loop, `settings.max_cache_entries_per_tenant`, `.store()`, `verify_equivalent()`, and an accepted key. No result was fabricated from the invalid snippets.

## Evaluation and Demo Results

All runs below used the final app code and the patched workspace-local runtime listed in `audit/evidence/validated-runtime.json`; no real LLM API was called. Exit codes are in `evaluation-exits.txt`.

| Command | Result | Verified artifacts / observed behavior |
|---|---|---|
| `python -m evaluation.run` | PASS, exit 0 | `metrics.csv` has 5 rows and the expected 7 columns; `tradeoff.png` and `ablation.png` have valid PNG signatures and positive dimensions. |
| `python -m evaluation.latency` | PASS, exit 0 | `latency.csv` has 9 rows and the expected 6 columns; both latency PNGs valid. The measured full-cache path explicitly asserts HIT. |
| `python -m evaluation.cascade` | PASS, exit 0 | `cascade.csv` has 21 rows and the expected 9 columns; cascade PNG valid. Configured default is 0.35. |
| `python -m evaluation.backend_compare` | UNAVAILABLE, exit 1 | Explicitly reports no Redis Stack / REDIS_URL. Pre-existing backend comparison CSV/PNG are **not** counted as current evidence. |
| `python demo.py` | PASS, exit 0 | MISS → HIT, number-mismatch rejection, volatile BYPASS, 429 during burst. Rate limit begins at burst item 14 after earlier demo calls. |
| `python demo_semantic.py` | PASS, exit 0 | Different-word password paraphrase HIT; Austria/Australia MISS; equivalent Austria paraphrase HIT. The Austria/Australia pair was below threshold in this run, so it does not independently prove entity-verifier activation. |

Output file sizes, PNG dimensions, CSV columns and row counts are recorded in `artifact-manifest.json`. Artifacts were regenerated; pre-existing files alone were never accepted as proof of execution.

Final evaluation: Tier-1 full policy accepts **5/15 positives (33.3%)** and **0/15 negatives**; Tier-1+NLI accepts **3/15 positives (20%)** and **0/15 negatives**. This is low recall on a small selected dataset, not proof of production correctness. Volatility controls: 5/5 detected and 0/4 false positives.

Final local median timings: embedding **46.51 ms**, KNN at 1,000 entries **0.121 ms**, Tier-1 **0.032 ms**, uncached bidirectional NLI **364.99 ms**, asserted full HIT **29.96 ms** (p95 **47.59 ms**). These stages were measured sequentially under changing host load and are not additive. The old NLI timing mostly measured memoization; the corrected inference timing is substantially higher. The 800 ms LLM reference and the cascade's 15× cost ratio are illustrative inputs, not measured service results. Cascade at 0.35 routed all labelled hard queries to strong and reported 46.7% illustrative cost reduction on its 40-query set.

## Test Coverage Gaps

Coverage below is the final 39-test run and measures statements, not branch/exhaustive behavioral coverage. A prior 19-test **intermediate-code** run measured 72%; it is not a directly comparable untouched-source baseline.

| Module | Coverage | Missing Scenarios |
|---|---:|---|
| `app/cache/redisearch_store.py` | 30% | Live FT.CREATE/search/schema mismatch, tenant TAG edge cases, connection failures, clear/TTL/eviction. |
| `app/cache/semantic_cache.py` | 73% | Live backend branch, reload failures, missing-row races, contention/rebuild interleavings. |
| `app/cache/storage.py` | 89% | WATCH collision/retry exhaustion and true multi-client transactions. |
| `app/cache/verifier.py` | 69% | Model load/predict failures, label layouts, cache eviction, out-of-domain equivalence. |
| `app/providers/openai_compat.py` | 90% | Malformed/truncated SSE, timeouts, non-2xx, cancellation. |
| `app/providers/breaker.py` | 100% | Covered lines do not prove concurrent transition ordering, probe expiry or late successes. |
| `app/rate_limit.py` | 88% | Real Redis Lua/NOSCRIPT, retry exhaustion, distributed clock skew. |
| `app/budget.py` | 90% | Retry exhaustion, day rollover, upstream attempt/cost reconciliation. |
| `app/main.py` | 90% | Model/index startup, dependency outages, input edge cases, stream disconnect/errors. |
| `app/embeddings.py` | 80% | Actual model load covered by evaluations separately; not by hash-based unit suite. |
| `app/config.py` | 84% | Every production guard and malformed settings combination. |

Tests added: cache expiry; cross-instance invalidation; 50 concurrent writes/3-entry cap; true LRU read recency; 50-request rate/budget contention; key secrecy; contraction/initial-entity cases; unsupported history; separate metrics credentials; half-open probe contention; midstream breaker failures; real HTTP adapter via MockTransport; multiline SSE HIT/MISS; separate lifespans; 50 concurrent HTTP requests; NLI fail-closed behavior; threshold bounds; production defaults; generic upstream 502; clock-query volatility.

Still needed: independent OS worker processes and Redis Stack; Redis failover/ACL/cluster behavior; real Lua/NOSCRIPT recovery; WATCH retry exhaustion; full cancellation/disconnect/timeout/truncated-stream matrix; exact expiry races; long-lived memory pressure; clean Python 3.11 install; real provider contracts (not paid smoke calls during this audit); model/schema migration; larger independent semantic evaluation.

## Performance Concerns

| Component | Observation | Recommendation |
|---|---|---|
| Inproc index | Revision GET per lookup, authoritative hash read per candidate; index rebuild does serial hash reads, vector parse and matrix allocation after writes | Pipeline reads, maintain a versioned snapshot, benchmark realistic Redis RTT and write-heavy workloads. |
| Cache storage | Each write reads full LRU sorted set; per-tenant locks serialize same-tenant cache operations | Fetch only eviction candidates / cardinality; measure tail latency and contention with multiple workers. |
| ML | Per-model lock prevents concurrent model mutation but serializes inference; thread cancellation cannot stop inference already running | Dedicated bounded model executor/batching; monitor CPU, queue depth and memory. |
| RediSearch client | Connection cleanup now reliable, but each operation constructs a client/pool | App-owned shared binary pool and schema validation after live correctness tests. |
| HTTP providers | Creates a new HTTPX AsyncClient per stream; no persistent connection reuse | Lifespan-owned provider clients with bounded pools and shutdown handling. |
| Benchmark validity | 15 positive/15 negative pairs and 5 volatile/4 stable controls; 800 ms upstream reference is illustrative, cascade quality is a routing-label proxy | Larger held-out data, real provider timing/cost, confidence intervals and end-to-end concurrency benchmarks. Do not present these charts as production SLO evidence. |

## Remaining Minor Findings

| ID | Finding | Recommendation |
|---|---|---|
| N01 | Checklist/docs differ from implemented API, thresholds, volatility and metrics credentials; comments still overstate cache/NLI/provider-call guarantees | Update public docs and comments to tested contracts; keep demonstration claims separate from production guarantees. |
| N02 | Transitives not fully locked/hashed, model revisions unpinned, Docker/service tags use mutable releases, CPU Torch unpinned | Lock and audit a target-platform dependency set and model/image revisions. |
| N03 | Revision keys, per-tenant locks/index metadata can outlive retired API keys; TTL cleanup leaves inproc memory until activity/changes | Tenant retirement cleanup and measurable global bounds. |
| N04 | Remaining `type: ignore[misc]` comments lack clear per-site explanations; Redis factories typed as Any weaken static guarantees | Tighten async Redis protocols and remove unnecessary suppressions. Lazy heavy imports are intentional, documented exceptions. |
| N05 | Readiness PING alone does not establish ongoing vector-index or upstream health; stream metrics omit some paths | Split liveness/readiness and monitor required dependencies without billable probes. |
| N06 | Dashboard claims cache clear succeeded without checking HTTP status, and has no general handling of other non-2xx JSON results | Check `response.ok`; show accurate authentication/upstream errors. |

## Compatibility and Deployment Notes

- The API remains stateless: multi-message/system/assistant histories now receive 422 instead of silently losing context.
- SSE `data:` payloads are JSON strings (except `[DONE]`); adapt consumers accordingly.
- Upstream failures no longer substitute mock answers. Configure a real fallback provider explicitly if required.
- New tenant hashing and RediSearch namespace intentionally avoid reuse of old entries. Old Redis data is **not deleted**; migration/retention is M02.
- `ENVIRONMENT=production`, strong API/metrics credentials, stable random `API_KEY_SALT`, Redis connectivity, a real provider and explicit CORS origins must be configured. `.env` was not modified.
- Grafana now requires `GRAFANA_ADMIN_PASSWORD`; infrastructure ports bind localhost.
- Real-Redis tests require explicit `TEST_ALLOW_REDIS_FLUSHDB=1` and a **disposable** database. Tests no longer issue `FLUSHALL`; the backend benchmark no longer resets the server.

## Verdict

**Ready for production: NO.** Local repairs materially improve correctness and security, but they are not a substitute for a green remote pipeline, current Docker validation and live Redis Stack/multi-worker proof. Close B01/B02 and resolve or explicitly accept the major risks for the intended domain. In particular, do not use semantic similarity alone to make correctness-critical decisions, and do not call this request-admission budget a monetary spend guarantee.

No remote state was changed to manufacture a green result. Local changes, tests, benchmark outputs and evidence remain available for review.

## Review Entry Points

The main repaired paths are `app/main.py` (lifespan, errors and SSE), `app/cache/semantic_cache.py` and `storage.py` (cache coherence/transactions), `app/cache/redisearch_store.py` (production vector storage), `app/providers/registry.py` and `breaker.py` (routing/recovery), `app/identity.py` (credential-derived IDs), and `tests/test_audit_regressions.py` (reproductions). The working-tree diff is uncommitted and ready for review; deployment remains blocked by the verdict above.
