# System Architecture

## VeriGate — LLM Gateway with Adaptive Self-Verifying Semantic Cache

This document describes the system design: components, how a request flows, the data
stores, and how the system scales. It is written so it can go directly into the "System
Design" chapter of the report.

---

## 1. Design goals

- **Correctness first** — never knowingly serve a wrong cached answer (this is the whole point).
- **Low latency on the hot path** — a cache hit must be dramatically faster than an LLM call.
- **Horizontally scalable** — multiple identical gateway replicas behind a load balancer;
  all shared state lives in Redis, not in a single process.
- **Provider-agnostic** — adding a new LLM provider is a small, isolated change.
- **Observable** — every decision (hit/miss/false-hit-rejected/failover) is measurable.

---

## 2. Component overview

```
                        ┌──────────────┐
   Client apps ───────► │ Load Balancer│
                        └──────┬───────┘
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
       ┌───────────┐    ┌───────────┐     ┌───────────┐
       │ Gateway   │    │ Gateway   │ ... │ Gateway   │   (stateless replicas)
       │ replica 1 │    │ replica 2 │     │ replica N │
       └─────┬─────┘    └─────┬─────┘     └─────┬─────┘
             └────────────────┼─────────────────┘
                              ▼
        ┌───────────────────────────────────────────────┐
        │                   REDIS                        │
        │  • vector index (semantic cache entries)       │
        │  • rate-limit counters (token buckets)         │
        │  • provider health / circuit-breaker state     │
        │  • usage & cost counters                        │
        └───────────────────────────────────────────────┘
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
       ┌──────────┐    ┌──────────┐     ┌──────────┐
       │Provider A│    │Provider B│     │  Mock/   │
       │ (LLM)    │    │ (LLM)    │     │  Echo    │
       └──────────┘    └──────────┘     └──────────┘

   Metrics ─► Prometheus ─► Grafana dashboard
   Persistent logs/usage ─► PostgreSQL (optional, for history)
```

Each gateway replica is **stateless**: it holds no request state locally, so any replica
can serve any request. All shared state is in Redis. This is what makes it a *distributed*
system rather than a single server.

---

## 3. Request lifecycle (the hot path)

A single `POST /v1/chat` request flows through an ordered pipeline of middleware/stages:

1. **Authentication** — resolve the API key; reject if invalid/unknown.
2. **Rate limiting** — atomically check-and-decrement the caller's Redis token bucket. If
   empty → `429 Too Many Requests`. (Atomic Lua script so it is correct across replicas.)
3. **Staleness check** — if the query is time-sensitive (volatile), skip the cache entirely
   and go to step 6. *(Novel component.)*
4. **Semantic cache lookup** *(Novel component)*:
   a. Embed the query into a vector.
   b. Query the Redis vector index for the nearest stored entry.
   c. Compute the **adaptive threshold** for this query.
   d. If similarity ≥ adaptive threshold → candidate hit; run **verification**.
   e. If verification passes → **cache HIT**: return stored answer (record metrics, stop).
   f. Else → **false hit rejected**: treat as miss, continue.
5. *(cache miss)*
6. **Provider routing** — select a provider by policy (health, cost, latency). Consult the
   circuit-breaker state in Redis; skip providers marked unhealthy.
7. **LLM call + streaming** — forward the request; stream tokens back to the client as they
   arrive (Server-Sent Events / chunked transfer). Do **not** buffer the whole response.
8. **Failover** — if the chosen provider errors/times out, trip its circuit breaker and
   retry the next provider (bounded retries, exponential backoff).
9. **Cache write** — once the full answer is known and the query is cacheable, store
   `{embedding, original_query, answer, metadata, timestamp}` in the Redis vector index.
10. **Metering** — record tokens, cost, latency, provider, and cache outcome to Redis
    counters and expose them via `/metrics`.

**Key subtlety (a good "hard problem" to discuss in the report):** streaming and caching
interact. Because tokens are streamed, the full answer is assembled *as it streams*; the
cache write happens after the stream completes. Similarly, failover during a partial
stream must be handled carefully (retry only if no tokens were sent yet).

---

## 4. Data stores and Redis usage

Redis does real work here, in **four distinct roles** — worth calling out explicitly:

| Role | Redis feature | Why |
|---|---|---|
| Semantic cache | **Vector index** (Redis Stack / RediSearch KNN) | Nearest-neighbour lookup of query embeddings. |
| Rate limiting | **Atomic counters + Lua** | Token-bucket per API key, correct across replicas. |
| Circuit breaker / health | **Keys with TTL** | Mark a provider unhealthy for N seconds after failures. |
| Usage & cost | **Counters / sorted sets** | Aggregate tokens/cost per key for metering & dashboards. |

**PostgreSQL (optional):** durable history — request logs, per-day usage — for the admin
dashboard and any analytics that shouldn't live only in Redis.

---

## 5. Provider abstraction

Every provider implements a small common interface:

```
interface Provider:
    name: str
    async chat(request) -> stream of tokens          # normalizes each vendor's API
    health() -> healthy | degraded | down
    price_per_1k_tokens: (input, output)
```

Adding a provider = implementing this interface. The **router** and **failover** logic are
provider-agnostic and only depend on this interface + the health state in Redis.

---

## 6. Scaling & reliability model

- **Horizontal scale:** add gateway replicas; the load balancer spreads traffic. No sticky
  sessions needed because replicas are stateless.
- **Shared state consistency:** rate-limit and health state are centralized in Redis, so
  all replicas agree.
- **Graceful degradation:** if a provider is down → failover. If Redis vector search is
  slow/unavailable → cache is bypassed (fail-open to the LLM), so the system still answers.
- **Backpressure:** rate limiting protects both the gateway and the upstream providers.

---

## 7. Observability

- **Prometheus** scrapes `/metrics` from every replica.
- **Grafana** visualizes: request rate, cache hit-rate, **false-hit-rejection rate**,
  p50/p95/p99 latency (hit path vs miss path), cost per API key, per-provider success rate
  and failover count.
- This dashboard is both an operational tool and the **evidence** for the evaluation
  chapter.

---

## 8. Security & safety notes

- API keys are hashed at rest; never logged in plaintext.
- Prompts/responses logging is configurable and can be disabled for privacy.
- The gateway never stores end-user credentials; it only holds *its own* API keys and the
  upstream provider keys (as server-side secrets/environment variables).
