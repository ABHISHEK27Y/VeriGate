# Quickstart — run, test, and understand VeriGate

This scaffold runs with **only Python** — no Redis install, no API keys, no Docker.

---

## 1. Run it (Windows, PowerShell)

```powershell
cd "D:\miniProject\7th sem\llm-gateway"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then:

```powershell
# A) Run the automated tests (proves each guarantee)
pytest -q

# B) Run the human-friendly demo (see MISS/HIT/reject/bypass/429 printed)
python demo.py

# B2) Run the SEMANTIC demo (real MiniLM model; first run downloads ~90MB).
#     Shows a paraphrase with different words HITTING, and the Austria/Australia trap
#     being avoided -- things the fast hashing embedder cannot do.
python demo_semantic.py

# C) Run it as a real HTTP server
uvicorn app.main:app --reload
#   -> open http://127.0.0.1:8000/ui      (interactive DASHBOARD - test everything with clicks)
#   -> open http://127.0.0.1:8000/health
#   -> open http://127.0.0.1:8000/metrics
#   -> open http://127.0.0.1:8000/docs    (interactive API, try requests in the browser)
```

Call it over HTTP:

```powershell
curl -X POST http://127.0.0.1:8000/v1/chat `
  -H "x-api-key: demo-key-123" -H "Content-Type: application/json" `
  -d '{"prompt":"how do I reset my password"}'
```

---

## 2. "How will I know it's working properly?"

You have **three independent signals**, strongest first:

**a) The test suite (`pytest`).** Each test encodes one promise of the system. If they pass,
those behaviours are correct:
| Test | What it proves |
|---|---|
| `test_health` | Server boots and reports status. |
| `test_auth_required` | Requests without a valid API key are rejected (401). |
| `test_cache_miss_then_hit` | A repeated/paraphrased query is served from cache. |
| `test_verifier_rejects_number_mismatch` | **The novelty:** a look-alike query with a different number is NOT served the wrong cached answer. |
| `test_volatile_query_bypasses_cache` | Time-sensitive queries are never cached. |
| `test_rate_limit_returns_429` | A burst of requests gets throttled. |
| `test_metrics_endpoint` | Metrics are exposed for monitoring. |

**b) The demo (`python demo.py`).** You literally see it happen. The key line to look for:
in section 2 the second query shows a **similarity ABOVE the threshold** (a naive cache
would call it a HIT) but VeriGate prints **MISS** — the verifier rejected the false hit.
That single line is the proof your contribution works.

**c) The metrics (`/metrics`) + Grafana (later).** Live counters:
`verigate_cache_total{result="hit|miss|bypass"}`, `verigate_false_hit_rejected_total`,
`verigate_rate_limited_total`, and latency histograms. When you build the evaluation
(Phase 7), these numbers *are* your results.

> Rule of thumb: **a feature isn't "done" until there's a test or a metric that proves it.**
> That habit is also what impresses examiners and interviewers.

---

## 3. "How can I test it?"

Three layers, all already wired:

1. **Unit/integration tests** — `pytest`. Add one test per new behaviour. They run on
   in-memory fakeredis, so they're fast and need no server.
2. **Manual / exploratory** — `uvicorn ... --reload`, then use `/docs` (Swagger UI) or
   `curl` to poke it by hand.
3. **Load testing (Phase 7)** — point **k6** or **Locust** at the running server using the
   free `mock` provider (zero API cost) to measure throughput, p99 latency, and confirm
   rate limiting + failover under pressure. This produces the performance graphs for the
   report.

For the **evaluation of the novelty** specifically, see `docs/EVALUATION_PLAN.md`: you build
a labelled benchmark of query pairs and compare VeriGate against a fixed-threshold baseline
on hit-rate vs. false-hit-rate. That comparison is the core result of the whole project.

---

## 4. "How will I manage Redis and all?"

**Right now: you don't have to.** With `REDIS_URL` blank, the app uses **fakeredis** — a
real Redis implementation running inside the Python process, in memory. Same code, same
commands, nothing to install or start. Perfect for development and tests.

**When you want a real Redis** (for persistence across restarts, multiple replicas, the
RediSearch vector upgrade, or to say "Redis" honestly on your resume), set `REDIS_URL` in
`.env`. Pick whichever is easiest for you:

| Option | How | Best for |
|---|---|---|
| **Redis Cloud / Upstash (free tier)** | Sign up, copy the connection URL into `REDIS_URL`. Nothing to install. | Easiest; works immediately; good for the deployed demo. |
| **Docker** | `docker run -p 6379:6379 redis/redis-stack` then `REDIS_URL=redis://localhost:6379/0`. (Redis Stack adds vector search for the Phase-3 KNN upgrade.) | Local dev once you install Docker Desktop. |
| **WSL** (you have it) | `wsl` → `sudo apt install redis-server` → `redis-server`. | No Docker needed, local. |
| **Memurai** | Native Redis-compatible server for Windows. | Windows without WSL/Docker. |

**Inspecting Redis (with a real server):**
```bash
redis-cli KEYS '*'                 # see all keys the gateway created
redis-cli SMEMBERS cache:ids       # ids of cached entries
redis-cli HGETALL cache:entry:<id> # a cached query + answer + vector
redis-cli HGETALL ratelimit:demo-key-123   # a token bucket's state
redis-cli MONITOR                  # watch every command live
```
(With fakeredis you can't use redis-cli, but you can inspect the same data in Python via
`from app.redis_client import get_redis`.)

**What lives in Redis** (see `docs/ARCHITECTURE.md` §4): the semantic cache entries + their
vectors, the rate-limit token buckets, provider health state (later), and usage counters.
Everything shared is centralized there so the gateway can scale to many replicas.

---

## 5. What's built vs. what's next

**Built now (runnable):** streaming proxy; **real OpenAI/Gemini provider** (via `LLM_PROVIDER`
+ key in `.env`) with the mock kept as failover; API-key auth; Redis token-bucket rate
limiting; the adaptive + self-verifying (Tier-1 + opt-in Tier-2 NLI) + staleness-aware
semantic cache with **real MiniLM embeddings**; **two vector backends** (in-process NumPy
default, or `VECTOR_BACKEND=redisearch` on Redis Stack — both verified); Prometheus metrics;
a 12-test suite; demos; and a full **evaluation harness** (accuracy + latency figures). See
`docs/RESULTS_LOG.md` for phase-by-phase results.

**Next (see `docs/IMPLEMENTATION_ROADMAP.md`):** bigger benchmark dataset, circuit breaker,
Grafana dashboard, and cloud deployment.
