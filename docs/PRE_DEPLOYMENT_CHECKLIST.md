# Pre-Deployment Checklist

Everything worth doing before exposing VeriGate publicly, grouped and prioritized. Check items
off as you go. Items marked **[blocker]** should be done before any public/multi-user deploy;
the rest are hardening depth. Cross-references to [SECURITY.md](SECURITY.md) in brackets.

---

## 1. Security (do these first)
- [x] **[blocker]** ✅ Per-tenant cache isolation — cache/index namespaced by `tenant_id` from
      the API key; isolation tests pass on both backends (Phase 14). [#1, #2]
- [x] **[blocker]** ✅ Per-key daily spend budget (Phase 18; cache hits are free). Global cap +
      spike alerting still to add. [#3]
- [ ] **[blocker]** Protect `/metrics` (internal token or private network only). [#6]
- [ ] **[blocker]** Move secrets to the host secret store; confirm `.env` is never in the image
      or git. [#7]
- [ ] TLS everywhere (proxy termination), HSTS, security headers, restrictive CORS. [#13]
- [ ] Strong random API keys; per-client keys; rotation policy; per-IP limits. [#15]
- [ ] Optional prompt-injection / output-moderation middleware. [#4, #16]
- [ ] Encrypt Redis at rest + in transit; PII redaction / do-not-cache-sensitive classifier. [#5]
- [ ] `pip-audit` / Dependabot in CI; rebuild on advisories. [#14]
- [ ] Production error handler that never leaks stack traces. [#17]

## 2. Reliability & resilience
- [x] ✅ **Circuit breaker** per provider (Redis TTL state) so a dead provider is skipped fast
      (Phase 18, `app/providers/breaker.py`).
- [ ] Timeouts on every provider call (already 60s — tune down) + bounded retries with backoff.
- [~] Cache TTLs ✅ (Phase 18, `CACHE_TTL_SEC`); **max size + eviction (LRU/LFU)** still to add;
      monitor memory. [#12]
- [ ] Graceful shutdown (drain in-flight requests) and startup readiness gating.
- [ ] Separate **liveness** vs **readiness** probes (`/health` is liveness; add readiness that
      checks Redis + model loaded).
- [ ] Load test at target RPS (k6) and record p50/p95/p99 + error rate under load.
- [ ] Chaos test: kill Redis / a provider mid-traffic and confirm graceful behaviour.

## 3. Observability
- [x] ✅ Grafana dashboard wired to Prometheus (hit-rate, false-hit-rejects, latency
      percentiles, request/cache rates) — Phase 16. Extend with per-key cost + provider panels.
- [ ] Structured JSON logging with request IDs; log levels per environment.
- [ ] Distributed tracing (OpenTelemetry) across gateway → provider.
- [ ] Alerts: error-rate, latency SLO breach, cost spike, cache memory, provider down.

## 4. Performance & scale
- [ ] Choose vector backend: `inproc` (single node) vs `redisearch` (multi-replica). [ARCH]
- [ ] If RediSearch: tune HNSW params (M, efConstruction, efRuntime); test at target corpus size.
- [ ] Connection pooling to Redis; async provider client reuse (avoid new client per request).
- [ ] Bake the embedding model into the image (or warm it at startup) to avoid first-request
      download latency; consider a smaller/faster embedder or a batching layer.
- [ ] Horizontal scale test: N replicas behind a load balancer sharing Redis.

## 5. Correctness & evaluation
- [ ] Expand the benchmark (Quora Question Pairs + generated paraphrases) and re-run the ablation.
- [ ] Tune adaptive-threshold weights on a validation split; report sensitivity.
- [ ] Gate Tier-2 NLI to borderline similarities; add an NLI budget. [#11]
- [ ] Regression tests for the cache decision (golden query pairs).

## 6. Data & compliance
- [ ] Data-retention policy for cached prompts/answers; TTLs enforce it.
- [ ] Privacy notice if end-user data is cached; consent where required.
- [ ] Backups/persistence for Redis (AOF/RDB) if the cache must survive restarts.

## 7. Delivery / ops
- [ ] CI: lint + `pytest` + `pip-audit` + build image on every push.
- [ ] Versioned, tagged images; rollback plan.
- [ ] `docker compose` for staging; IaC (Terraform) for the cloud target if applicable.
- [ ] Runbook: how to rotate keys, flush cache, scale, and roll back.
- [ ] Cost dashboard + monthly budget alert with the provider.

---

## Minimal "safe public demo" set (if you only do a few)
1. Per-tenant cache isolation. 2. Per-key spend cap. 3. Lock `/metrics` + secrets in a store.
4. TLS + security headers + CORS. 5. Cache size cap + TTL. 6. Circuit breaker + tuned timeouts.
7. Grafana + alerts. Do these and the gateway is genuinely deployable.
