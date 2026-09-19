# Code Walkthrough (viva prep)

Read this to be able to defend **every file** in the project. It maps the codebase, traces a
request end-to-end, explains each module and *why* it's built that way, and lists likely
examiner questions with crisp answers.

Total: ~1,400 lines of app code across small, single-responsibility modules.

---

## 1. Repo map

```
app/
  main.py            FastAPI app: routes, request pipeline, tenant derivation, UI serving
  config.py          all settings (env / .env), one Settings object
  schemas.py         Pydantic request/response models
  redis_client.py    real Redis vs in-memory fakeredis (same code path)
  rate_limit.py      token-bucket rate limiter (Lua on real Redis, WATCH fallback)
  embeddings.py      query -> vector (MiniLM real, or hash fallback for tests)
  complexity.py      query-hardness score -> cost-aware cascade routing
  metrics.py         Prometheus counters/histograms
  cache/             THE CONTRIBUTION
    policy.py          the cache decision (shared by gateway + evaluation)
    threshold.py       Sub-contribution A: adaptive per-query threshold
    verifier.py        Sub-contribution B: Tier-1 structural + Tier-2 NLI verifier
    volatility.py      Sub-contribution C: staleness detection
    semantic_cache.py  ties it together, per-tenant, two vector backends
    redisearch_store.py RediSearch/HNSW backend (distributed vector index)
  providers/
    base.py            Provider interface
    mock.py            free deterministic provider (+ flaky, for failover demos)
    openai_compat.py   OpenAI/Gemini streaming provider
    registry.py        provider order, failover, cost-aware cascade routing
  static/dashboard.html  the web UI (served at / and /ui)
evaluation/          benchmarks that produce the figures (run/cascade/latency/…)
tests/               pytest suite (15 tests)
```

**One-line thesis:** an LLM gateway whose cache reuses answers by *meaning* but *verifies*
every hit, so it cuts cost/latency without ever serving a wrong cached answer.

---

## 2. The request lifecycle (how the files connect)

`POST /v1/chat` in [`main.py`](../app/main.py) runs this pipeline:

1. **Auth** — `_auth()` checks the API key against `settings.api_key_set`.
2. **Tenant** — `_tenant(api_key)` = `"t_" + sha256(key)[:16]`. Everything cache-related is
   scoped to this (security isolation).
3. **Rate limit** — `rate_limiter.allow(api_key)` (Redis token bucket) → 429 if empty.
4. **Cache lookup** — `semantic_cache.lookup(prompt, tenant)`:
   - volatility check (`volatility.is_volatile`) → BYPASS if time-sensitive,
   - embed (`embeddings.embed`) → nearest neighbour (in-process matrix or RediSearch),
   - decision (`policy.CachePolicy.decide`): adaptive threshold + verifier.
   - HIT → return the cached answer immediately (fast, free).
5. **Miss** → `registry.route_stream(prompt)` picks a provider (cascade + failover) and streams
   the answer; the full text is assembled.
6. **Store** — `semantic_cache.store(prompt, answer, tenant)` (unless volatile).
7. **Meter** — Prometheus counters + latency histogram in [`metrics.py`](../app/metrics.py).

That's the whole system. Everything else supports one of these steps.

---

## 3. File-by-file

### `config.py`
A single `pydantic_settings.BaseSettings` subclass. Every knob (Redis URL, rate limits,
cache threshold, embedding/vector backend, providers + keys, cascade, NLI) is here with a
default, read from environment/`.env`. `api_key_set` parses the comma-separated `API_KEYS`.
**Why:** one typed, validated source of config; no scattered `os.getenv`.

### `redis_client.py`
`get_redis()` returns a real Redis client if `REDIS_URL` is set, else an in-memory
`fakeredis` client — **same interface either way**. **Why:** the whole app (and tests) run
with zero infrastructure, and switch to real Redis by setting one env var.

### `rate_limit.py`
A **token-bucket** per API key. Two implementations, auto-selected: an atomic **Lua script**
on real Redis (correct across replicas), and a **WATCH/MULTI optimistic-transaction** fallback
where Lua isn't available (fakeredis). **Why:** correctness under concurrency + portability.
*Viva:* "why token bucket?" → allows bursts up to capacity, refills smoothly; classic,
distributed-safe.

### `embeddings.py`
`embed(text)` returns an L2-normalized vector. Backend is pluggable: `minilm`
(sentence-transformers `all-MiniLM-L6-v2`, real semantics) or `hash` (a fast crc32 hashing
embedder, deterministic, no model download — used in tests). `cosine()` is just a dot product
because vectors are normalized. **Why:** real semantics in prod, instant/deterministic tests.

### `cache/threshold.py` — Sub-contribution A
`adaptive_threshold(query, density)` computes the similarity cutoff **per query** from
features: entity density, presence of numbers, shortness, and neighbourhood density. Fact-dense
/ short queries get a **stricter** threshold; long open-ended ones a looser one. **Why:** a
single global threshold can't both save money and avoid wrong answers.

### `cache/verifier.py` — Sub-contribution B
Before serving a candidate hit, confirm the two queries are truly equivalent **without calling
the LLM**:
- **Tier-1 (structural, ~microseconds):** numbers must match (5 vs 50 GB), negation must match
  (safe vs not safe), named entities must match (Austria vs Australia).
- **Tier-2 (semantic, opt-in):** a small **NLI cross-encoder** checks bidirectional entailment;
  catches related-topic look-alikes (reset password vs reset router). Cached per pair.
**Why:** similarity ≠ equivalence; this is what makes hits *correct*. Tier-2 is opt-in because
it trades recall/latency for max correctness (shown in the evaluation).

### `cache/volatility.py` — Sub-contribution C
`is_volatile(query)` flags time-sensitive queries (today/now/price/weather…) that must never
be cached. **Why:** a cached "weather today" would go stale.

### `cache/policy.py`
`CachePolicy.decide(query, candidate, sim, density)` = the single decision function:
threshold → verifier → HIT/MISS, with flags `use_adaptive`, `use_verifier`, `use_nli`.
**Why it exists:** the **live gateway and the evaluation call the exact same function**, so a
measured result equals shipped behaviour, and toggling flags gives the ablation study.

### `cache/semantic_cache.py`
Ties it together, **partitioned per tenant** and supporting **two vector backends**:
- in-process: one NumPy matrix per tenant → a lookup is a single matrix-vector product (fast).
- RediSearch: delegates to `redisearch_store` (shared HNSW index, tenant-filtered).
`lookup/store/clear` are all tenant-scoped (`cache:*:<tenant>` keys / tenant TAG). **Why:** the
in-process index removed the O(n) parse bottleneck; tenancy closes the cross-tenant leak.

### `cache/redisearch_store.py`
The production vector index: `FT.CREATE` an HNSW cosine index with a `tenant` TAG, `add()`
stores float32 vectors, `knn()` runs `(@tenant:{t})=>[KNN k @vec]` (isolation + ANN). Uses a
binary-safe Redis client. **Why:** exact in-process search doesn't scale to millions or share
across replicas; RediSearch does.

### `complexity.py` + cascade
`complexity_score(query)` (0..1) and `is_hard()` estimate query difficulty from length,
reasoning words, code/math, comparisons. **Why:** power the cost-aware cascade — cheap model
for easy queries, escalate only hard ones.

### `providers/`
`base.Provider` = interface (`stream()`, `health()`). `mock.MockProvider` = free deterministic
answers (`FlakyProvider` for failover demos). `openai_compat.OpenAICompatibleProvider` = one
class for OpenAI **and** Gemini (Gemini via its OpenAI-compat endpoint), parsing SSE streams.
`registry` builds the provider order and routes: **failover** (try in order, mock last) plus
the **cascade** (`_order_for(prompt)` puts strong-first for hard queries, cheap-first for easy,
keeping the other as failover). **Why:** provider-agnostic core; reliability + cost control.

### `metrics.py` / `schemas.py` / `main.py`
`metrics.py` defines Prometheus counters (requests, cache outcomes, false-hit rejects,
rate-limits) + a latency histogram. `schemas.py` = `ChatRequest`/`ChatResponse`. `main.py`
wires routes: `/v1/chat`, `/v1/chat/stream`, `/health`, `/metrics`, `/admin/cache/clear`,
and serves the dashboard at `/` and `/ui`.

### `static/dashboard.html`
A dependency-free single-page UI served **same-origin** by the gateway (no CORS). Talks to
`/v1/chat`, `/health`, `/admin/cache/clear`. Explains the contribution, shows animated results,
and provides the interactive playground.

### `evaluation/` and `tests/`
`evaluation/*` produce the figures: `run.py` (accuracy/ablation + the trade-off graph),
`cascade.py` (cost-vs-quality), `latency.py` + `backend_compare.py` (latency/scaling).
`tests/*` (15) cover health, auth, cache hit/miss, verifier, volatility, rate-limit, metrics,
**tenant isolation**, and **cascade routing**.

---

## 4. Key design decisions (be ready to defend these)

1. **One shared `CachePolicy`** for gateway + evaluation → results equal shipped behaviour; the
   ablation is just flag toggles.
2. **Verifier over a looser threshold** → you get high recall *and* correctness; the threshold
   alone forces a bad trade-off.
3. **Tier-2 NLI is opt-in** → data showed it maximizes correctness but costs recall/latency and
   is redundant once the adaptive threshold is on. Defaults reflect the evidence, not hype.
4. **Per-tenant partitioning** → identified cross-tenant leakage as the defining risk of a
   *semantic* cache in the threat model, then eliminated it (tests on both backends).
5. **In-process index first, RediSearch for scale** → benchmark showed the O(n) cost was
   *parsing*, not the algorithm; vectorising fixed it; RediSearch is the multi-replica path.
6. **fakeredis + hash embedder + mock provider** → the whole system runs and is tested with no
   infra, no keys, no cost; real backends switch on via env vars.
7. **Failover always ends at mock** → the gateway never hard-fails on a provider outage.

---

## 5. Likely viva questions → short answers

- **What's novel? Doesn't GPTCache exist?** The *system* isn't novel; the *caching method* is:
  adaptive per-query thresholding + a self-verifier + staleness detection, which eliminate the
  false-hits static-threshold caches suffer. Proven: 0% false-hit vs 46.7% baseline.
- **Semantic vs exact cache?** Exact matches identical text; semantic matches *meaning* (via
  embeddings), so paraphrases hit — but "close" can be wrong, which the verifier guards.
- **How do you avoid serving a wrong answer?** Adaptive threshold rejects low-similarity; the
  verifier rejects number/negation/entity mismatches and (Tier-2) non-entailing look-alikes.
- **How does it scale?** Stateless replicas + shared Redis; in-process vector index for one node
  (sub-ms), RediSearch/HNSW for millions across replicas.
- **Biggest security risk and fix?** Cross-tenant cache leakage; fixed by partitioning the cache
  per tenant (key + index namespace), verified by isolation tests.
- **How is it evaluated?** A labelled benchmark of paraphrase pairs + hard negatives; measure
  hit-rate vs false-hit-rate vs a static baseline + ablation; plus latency and cost-cascade
  benchmarks. All reproducible (`python -m evaluation.*`).
- **What would you do next?** Per-key spend budgets, learned threshold/complexity classifiers,
  a bigger dataset, and cloud deployment (all in ENHANCEMENTS.md).
- **Why FastAPI / Redis / MiniLM?** Async + streaming + auto OpenAPI; Redis does vectors + rate
  limits + state in one store; MiniLM is a small, fast, strong sentence embedder.

---

## 6. How to run it in the viva (2 commands)
```bash
uvicorn app.main:app --reload        # then open http://127.0.0.1:8000/ui  (live demo)
python -m evaluation.run             # regenerates the results figures
```
Have the UI open (playground: paraphrase → HIT, look-alike → blocked, "today" → BYPASS) and the
`tradeoff.png` / `cascade.png` figures ready. That covers demo + results + contribution.
