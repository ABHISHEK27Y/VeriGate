# Production Architecture (Target Design)

Extends [ARCHITECTURE.md](ARCHITECTURE.md) (which covers the current implementation) with the
**production-grade target**: deployment topology, trust boundaries, data model, the full
request sequence, and where each security control sits.

---

## 1. Deployment topology

```
                          Internet
                             │  HTTPS
                    ┌────────▼─────────┐
                    │  TLS proxy /     │   Caddy/Nginx/host LB
                    │  Load balancer   │   - TLS, HSTS, security headers, CORS
                    └────────┬─────────┘   - request size limits
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
      ┌────────────┐  ┌────────────┐  ┌────────────┐
      │ Gateway r1 │  │ Gateway r2 │  │ Gateway rN │   stateless replicas (Docker)
      │  FastAPI   │  │  FastAPI   │  │  FastAPI   │   - auth, rate limit, cache
      └─────┬──────┘  └─────┬──────┘  └─────┬──────┘   - verifier, router
            └───────────────┼───────────────┘
                 ┌──────────┴───────────┐
                 ▼                      ▼
        ┌─────────────────┐    ┌──────────────────┐
        │  Redis Stack     │    │  Secret manager  │  (SSM/Vault/host)
        │  - vector index  │    │  provider + GW    │
        │  - rate buckets  │    │  keys, rotated    │
        │  - health/state  │    └──────────────────┘
        │  - usage counters│
        └─────────────────┘
                 │ (shared, TLS + at-rest encryption)
                 ▼
        ┌──────────────────────────────────────────┐
        │  LLM providers (OpenAI / Gemini / ...)    │  egress allowlist
        └──────────────────────────────────────────┘

   Metrics: each replica → Prometheus → Grafana + Alertmanager
   Traces:  OpenTelemetry → collector
```

**Why this shape:** replicas are **stateless** (all shared state in Redis), so scaling is "add
replicas behind the LB." The LB owns TLS and edge protections; Redis is the shared brain;
secrets live outside the app; observability is out-of-band.

---

## 2. Trust boundaries (where controls live)

| Boundary | Crossing | Controls |
|---|---|---|
| Internet → LB | untrusted requests | TLS, rate limit (edge), size limits, WAF/CORS |
| LB → Gateway | authenticated requests | API-key auth, per-key rate + spend limits |
| Gateway → Redis | trusted internal | network isolation, TLS, at-rest encryption, **per-tenant namespacing** |
| Gateway → Provider | egress | host allowlist (anti-SSRF), timeouts, circuit breaker, key from secret store |
| Gateway → Metrics | internal | private network / token on `/metrics` |

**Key invariant:** every cache read/write is scoped to the caller's `tenant_id` (derived from
the API key). The cache is never shared across a trust boundary — this closes the
cross-tenant leakage/poisoning/timing risks (SECURITY #1/#2/#9/#10).

---

## 3. Data model (Redis)

| Key / structure | Holds | Notes |
|---|---|---|
| Vector index (RediSearch) or `cache:entry:<tenant>:<id>` HASH | `{query, answer, vec, ts, ttl}` | **namespaced by tenant**; TTL per entry |
| `ratelimit:<tenant>:<key>` HASH | token-bucket `{tokens, ts}` | atomic Lua / WATCH |
| `budget:<key>:<day>` counter | tokens/cost spent | enforces spend caps |
| `health:<provider>` key w/ TTL | circuit-breaker state | skip dead providers |
| `usage:<key>` counters / sorted sets | tokens, cost, hits | metering + dashboards |

Vectors stored as FLOAT32 bytes (RediSearch) or CSV (in-process). PII-sensitive entries are
redacted or not cached (staleness/sensitivity classifier).

---

## 4. Request sequence (production)

1. **TLS/LB**: terminate TLS, apply edge rate limit + size cap, CORS.
2. **Auth**: resolve API key → `tenant_id`; reject if invalid (401).
3. **Rate limit + budget**: atomic token bucket; check per-key spend cap (429 if exceeded).
4. **Staleness**: skip cache for volatile/sensitive queries.
5. **Cache lookup** *(tenant-scoped)*: embed → KNN (in-process or RediSearch) → adaptive
   threshold → Tier-1 verify → optional Tier-2 NLI. HIT ⇒ return (metrics, done).
6. **Route + guardrail**: pick a healthy provider (circuit breaker); optional injection guard.
7. **Call + stream**: forward with timeout; stream tokens; on error, **failover** (bounded).
8. **Cache write** *(tenant-scoped, TTL)*: store the verified answer.
9. **Meter + trace**: record tokens/cost/latency/outcome; emit metrics + span.

---

## 5. Failure modes & degradation

| Failure | Behaviour |
|---|---|
| A provider is down | circuit breaker trips → failover to next → mock as last resort |
| Redis unavailable | cache fails **open** (skip cache, still answer via provider) |
| Vector search slow/error | bypass cache for that request |
| Embedding model load fails | fall back to hash embedder (degraded matching) |
| Budget exceeded | 429 with a clear message (protects the bill) |
| Rate limit exceeded | 429 (protects providers + fairness) |

The system prefers **answering (possibly uncached)** over failing, except where a limit is a
deliberate protection (budget/rate).

---

## 6. Scaling notes
- **Vertical of one node**: `inproc` vector index (sub-ms, exact) is ideal.
- **Horizontal / large corpus**: `redisearch` shared HNSW so all replicas see one index.
- Redis is the scaling pivot; shard it when a single node's memory/throughput is exceeded.
- Embedding is the hot-path cost (~10 ms); batch or cache embeddings, or use a faster model.

---

## 7. What is already built vs. target
Built: stateless FastAPI gateway, auth, rate limiting, the adaptive/self-verifying/staleness
cache with two vector backends, provider failover (mock/OpenAI/Gemini), Prometheus metrics.
Target additions (see [PRE_DEPLOYMENT_CHECKLIST.md](PRE_DEPLOYMENT_CHECKLIST.md)): tenant
namespacing, spend budgets, circuit breaker, TLS/edge controls, secret manager, Grafana +
alerts, cache eviction/TTL.
