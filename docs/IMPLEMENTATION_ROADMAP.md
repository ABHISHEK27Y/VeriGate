# Implementation Roadmap

A phased, week-by-week plan that goes from an empty repo to an evaluated, deployed system.
Built so that the **novel contribution and its evaluation are protected** — secondary
features are staged and some are explicitly optional if time runs short.

Assume ~14 working weeks. Adjust to your semester calendar.

> **Progress (2026-09-18):** ✅ Phases 0–4 (foundation, proxy+streaming, auth+rate limiting,
> baseline cache, and the novel adaptive/self-verifying cache with real MiniLM embeddings),
> and ✅ a first pass of Phase 7 (evaluation harness + trade-off/ablation figures) are DONE.
> Results are recorded in [`RESULTS_LOG.md`](RESULTS_LOG.md). Also DONE since: Tier-2 NLI
> verifier, latency benchmark, vectorised index, and the **RediSearch/HNSW backend verified on
> a live Redis Stack** (`VECTOR_BACKEND=redisearch`). Remaining: real LLM providers, circuit
> breaker, Grafana, dataset expansion, and deployment.

---

## ✅ Phase 0 — Foundations (Week 1)
- Repo setup, virtual env, linting/formatting, `.env` handling, Docker skeleton.
- Literature survey started: read GPTCache, Portkey/LiteLLM docs, semantic-cache papers.
- **Milestone:** repo runs a "hello" FastAPI server in Docker.
- **DoD:** `docker compose up` serves a health endpoint.

## ✅ Phase 1 — Basic gateway proxy + streaming (Weeks 2–3)
- `POST /v1/chat` accepts a request and forwards to **one** real provider.
- Implement **streaming** passthrough (SSE/chunked) — no full-response buffering.
- Provider interface abstraction; add a **mock/echo provider** (free, for load tests).
- **Milestone:** end-to-end streamed answer from a real LLM through the gateway.
- **DoD:** a client sees tokens stream in; mock provider works with zero API cost.

## ✅ Phase 2 — Auth + Redis rate limiting (Week 4)
- API-key auth (hashed keys).
- **Token-bucket rate limiting in Redis** via atomic Lua script (correct across replicas).
- `429` on limit exceeded; per-key limits configurable.
- **Milestone:** a hammering client gets throttled correctly.
- **DoD:** concurrency test shows no over-admission across 2 replicas.

## ✅ Phase 3 — Baseline semantic cache (Weeks 5–6)  ← foundation for novelty
- Embed queries; store `(query, embedding, answer)` in **Redis vector index**.
- Nearest-neighbour lookup; **static threshold** hit/miss (this is the baseline you'll beat).
- Wire cache into the request pipeline; record hit/miss metrics.
- **Milestone:** repeated/paraphrased queries hit the cache; measurable hit-rate.
- **DoD:** demonstrable cache hit with latency ~10x faster than the LLM path.

## ✅ Phase 4 — THE NOVEL CONTRIBUTION (Weeks 7–9)  ← the core  [first version done; real embeddings in]
- **Week 7 — Adaptive thresholding:** NER + numeric + length + neighbourhood-density
  features; `T(q)` function; config for weights.
- **Week 8 — Self-verification:** Tier-1 lexical/entity/number/negation checks; Tier-2
  lightweight NLI cross-encoder; conservative reject-on-doubt policy.
- **Week 9 — Staleness detection:** volatility keywords + optional classifier + TTLs.
- **Milestone:** the false-hit example ("Austria" vs "Australia") is **caught and correctly
  re-answered**, live.
- **DoD:** each component toggleable via config (needed for ablation).

## Phase 5 — Routing, failover, circuit breaker (Week 10)
- Multi-provider router (policy: health → cost → latency).
- Automatic **failover** with bounded retries + backoff.
- **Circuit breaker** state in Redis (TTL-based) to skip dead providers.
- **Milestone:** killing a provider mid-traffic triggers seamless failover.
- **DoD:** failover visible in logs/metrics; no client-visible error during a single-provider outage.

## Phase 6 — Observability (Week 11)
- Prometheus `/metrics`: request rate, hit-rate, **false-hit-rejection rate**, latency
  percentiles (hit vs miss vs verifier), cost per key, per-provider success/failover.
- Grafana dashboard.
- **Milestone:** one screen shows the system's health + the cache's behaviour.
- **DoD:** dashboard populated under live traffic.

## 🚧 Phase 7 — Evaluation (Weeks 12–13)  ← generates the results chapter  [harness + first figures done; expand dataset next]
- Build the **benchmark dataset** (positives, hard negatives, volatile set).
- Run baselines (no-cache, static-`T` sweep, exact-match) + VeriGate + ablations.
- Produce the **false-hit-rate vs hit-rate** graph and latency/cost tables.
- Load test (k6/Locust) via mock provider for throughput + rate-limit/failover validation.
- **Milestone:** the "money graph" clearly shows VeriGate beating the baseline curve.
- **DoD:** every figure regenerable by one script; raw CSVs committed.

## Phase 8 — Deploy + polish + write-up (Week 14)
- Dockerize fully; deploy to **Render/Fly.io/AWS**; public demo URL.
- Minimal **Next.js admin dashboard** (keys, live usage/cost) — plays to your React strength.
- Finalize report (using the docs in this repo as chapters) + slides + demo video.
- **Milestone:** anyone with the link can hit the gateway; report complete.
- **DoD:** live demo + reproducible eval + submitted report.

---

## Priority / cut-list (if time runs short)

**Never cut (this is the project):** Phases 3, 4, 7 — the cache, the novelty, the evaluation.

**Cut/simplify last, in this order if needed:**
1. Next.js admin dashboard → replace with a simple metrics page or CLI.
2. PostgreSQL history → keep everything in Redis.
3. Third provider → two providers is enough to show routing/failover.
4. Learned classifier for adaptive-T → keep the heuristic version.

---

## Definition of "done" for the whole project

- [ ] Live, deployed gateway (public URL) with streaming, auth, rate limiting.
- [ ] Adaptive + self-verifying + staleness-aware semantic cache, each toggleable.
- [ ] Multi-provider routing with working failover + circuit breaker.
- [ ] Grafana dashboard with the key metrics.
- [ ] Benchmark + reproducible evaluation + the false-hit-rate vs hit-rate figure.
- [ ] Report + slides + demo video.
