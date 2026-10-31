# Production configuration and release requirements

The gateway defaults to `CACHE_MATCH_MODE=exact`. It reuses only an identical UTF-8 prompt
within the same credential-derived tenant and model/policy namespace. This avoids the
known role-reversal, lowercase-entity and number-association failures in approximate
matching. Cached answers can still become stale or originate from an incorrect upstream
answer. Disable caching for workloads requiring a fresh response on every request.

`CACHE_MATCH_MODE=semantic` is an explicit opt-in. Structural checks and optional NLI are
statistical safeguards, not proof of equivalence. Calibrate on domain-specific negative
examples before enabling this mode. Historical evaluation results apply only to their
small recorded dataset. Semantic demos must explicitly select this mode.

For an **experimental local** answer-aware policy, also set
`ANSWER_POLICY_ARTIFACT=app/cache/artifacts/answer_policy_v1.json`. The gateway
loads the pinned, hash-checked artifact at startup, passes the actual cached
answer to it, and sends VERIFY and REJECT decisions to the provider. The current
controlled result is in [RESULTS_ANSWER_AWARE.md](RESULTS_ANSWER_AWARE.md).
Its authored cases do not establish a production safety threshold. Keep exact
matching for production until a representative independent evaluation exists.

`ANSWER_POLICY_PREWARM=false` is the default. With semantic mode and an answer
policy artifact, set it to `true` to load and test the pinned NLI model during
startup. The app does not become ready until this succeeds; a failed required
prewarm fails startup. This moves model-load time before the first semantic
request and does not reduce total startup-plus-request time. Allow enough
startup time and memory for the model. Exact mode does not load NLI.

The single-turn request accepts `prompt` or one `user` message, plus optional
`cache_bypass: true`. Unknown fields, including unsupported system messages and
generation parameters, return 422. Bypass skips both cache reads and writes but
still consumes rate-limit and admitted-miss/bypass budget. Empty or failed
provider outputs are never cached. A successful provider answer is returned even
if a later cache write fails. A cache lookup failure is treated as a miss, while
Redis failure in required rate or budget admission returns 503.

When cascade routing is enabled, cache entries are partitioned by the intended
cheap/strong route. A fallback model's answer is returned but not cached under
the failed route. JSON responses include actual and intended provider names and
`fallback_used`; streaming responses expose provider names in headers. This is
model provenance, not a claim that different model outputs have equal quality.

## Installation and reproducibility

Use Python 3.11 and the checked-in hashed lock:

```sh
pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock
pip install --no-deps --no-build-isolation -e .
```

The container installs `requirements-runtime.lock` without development tools. Both locks
pin transitive packages and artifact hashes; CPU Torch comes from its official index.
Container/service images are pinned to Docker Hub digests. Embedding and NLI defaults
pin Hugging Face commit revisions. Update locks and image/model revisions deliberately,
rerun security scans, and retest. Hosted provider aliases can change outside this project;
choose versioned model IDs where available and bump `CACHE_EPOCH` after external policy,
knowledge or upstream behavior changes.

## Runtime configuration

Set `ENVIRONMENT=production`, a shared `REDIS_URL`, private `API_KEYS`, a random stable
`API_KEY_SALT` of at least 32 characters, a private `METRICS_TOKEN`, and a real
`LLM_PROVIDER` with its credential. Production startup rejects unsafe defaults and Redis
without a finite `maxmemory`. Configure Redis `maxmemory-policy noeviction` so capacity
failures are visible. Compose provides a 512 MiB limit. Run behind TLS with explicit
`CORS_ORIGINS`; blank means same-origin only. Secrets are deployment inputs, never image
contents. No mock fallback is inserted for real providers.

Configuration is validated and frozen per app at startup. Use `create_app(config)` for
multiple applications in one process; replace/restart an app to change configuration.

| Setting | Default | Meaning |
|---|---:|---|
| `CACHE_TTL_SEC` | 3600 | Positive lifetime for entries and metadata |
| `MAX_CACHE_ENTRIES_PER_TENANT` | 256 | Finite LRU entry limit |
| `MAX_CACHE_ENTRY_BYTES` | 65536 | Encoded payload bound, including stored vectors |
| `MAX_CACHED_TENANTS` | 16 | Per-worker local index tenant bound |
| `MAX_REQUEST_BYTES` | 65536 | Actual request body limit; excess returns 413 |
| `MAX_CONCURRENT_REQUESTS` | 64 | Per-worker admission limit held through streaming; excess returns 503 |
| `REQUEST_BODY_TIMEOUT` | 10 | Seconds allowed for the complete request body |
| `MAX_RESPONSE_CHARS` | 1000000 | Maximum assembled upstream response size |
| `DAILY_REQUEST_BUDGET` | 0 | Admitted misses/bypasses per key and UTC day; zero disables this limit |
| `PROVIDER_TIMEOUT` | 30 | Total upstream deadline in seconds |
| `PROVIDER_FIRST_TOKEN_TIMEOUT` | 8 | Maximum first-token wait per attempt, also limited by equal share of total deadline |
| `PROVIDER_STREAM_IDLE_TIMEOUT` | 8 | Maximum idle time between tokens, within the total deadline |

The daily request budget **does not count provider retries, cascade attempts, tokens or
money**. Use provider-side spending limits for monetary enforcement. Hits do not consume
admission budget. Inference capacity is retained until its thread finishes even when the
request is cancelled. Local tenant locks are a fixed-size stripe array. Retired namespaces
expire through TTL; old pre-v3 keys from an earlier deployment need an explicit migration
cleanup after rollback requirements are satisfied. Never indiscriminately flush shared Redis.

## Monitoring and health

`/live` checks process liveness. `/ready` (also `/health`) checks Redis and, in semantic
RediSearch mode, the expected vector schema. These endpoints explicitly report that paid
provider health is configuration-only; no billable synthetic request is sent.

`/metrics` accepts `Authorization: Bearer <METRICS_TOKEN>` or the legacy
`X-Metrics-Token` header. Create a private file containing only that token, point
`METRICS_TOKEN_FILE` at it, and set `GRAFANA_ADMIN_PASSWORD` before starting the observability
Compose file. Prometheus reads the token from a Docker secret; it is not embedded in YAML.
In production, `/health` exposes status only. `/admin/config` requires an API
key for configuration details. The dashboard asks for the key rather than
embedding a demo credential. Stage histograms and bounded outcome counters
are available through authenticated `/metrics`; their labels contain no prompt,
answer, or credential text.

For multiple workers, set `PROMETHEUS_MULTIPROC_DIR` **before starting Python** to a shared,
writable, empty directory for that one deployment. Clean that directory only while all
workers are stopped; old process files otherwise inflate counters. Each worker writes
Prometheus multiprocess files and `/metrics` merges them. Single-process deployments need
no extra configuration. Counters aggregate the process/deployment, including multiple
app instances if hosted in the same process. Streaming completions and stream errors are
counted; the end-to-end metric measures gateway handling, not external network latency.

## Release gate

A local unit-test pass is not production approval. Require a fresh green CI run for the
reviewed revision, a current Docker build, Redis Stack tests including schema validation,
and independent-worker cache/rate/breaker checks. Run load tests at the intended tenant
count, cache size and provider latency; the research benchmark does not establish an SLO.
Historical findings and unresolved release checks are listed in the
[audit report](audit/AUDIT_REPORT.md); verify the current revision separately.
