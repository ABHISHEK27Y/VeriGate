# RediSearch Vector Index — Production Scaling Path

This documents the distributed, multi-replica form of the KNN index. It complements (does
not replace) the in-process vectorised index that ships by default.

> **Status: VERIFIED (2026-09-18).** Tested end-to-end against a live Redis Stack — the gateway
> runs on this backend via `VECTOR_BACKEND=redisearch`, and a latency comparison is in
> `RESULTS_LOG.md` Phase 10. Enable it by pointing `REDIS_URL` at Redis Stack and setting
> `VECTOR_BACKEND=redisearch`.

## Why two indexes?

| | In-process vectorised index (default, shipped) | RediSearch/HNSW index (this doc) |
|---|---|---|
| Where vectors live | one NumPy matrix per gateway process | inside Redis, shared by all replicas |
| Lookup | single matrix-vector product (exact) | HNSW approximate nearest neighbour |
| Speed | sub-millisecond to ~tens of thousands | sub-millisecond to **millions** |
| Multi-replica | each replica holds its own copy | one shared index, always consistent |
| Needs | nothing (numpy) | **Redis Stack** (RediSearch module) |

The in-process index already removed the original O(n) parse bottleneck (KNN@1000: ~293 ms →
~0.04 ms; see `RESULTS_LOG.md` Phase 9). RediSearch is the next step **when you need
horizontal scale or millions of vectors** — a great "future work / production" section for
the report, and the reason to say "Redis" fully honestly on a CV.

## Code

A ready-to-run reference backend is in [`app/cache/redisearch_store.py`](../app/cache/redisearch_store.py):
`ensure_index()`, `add()`, `knn()`, plus `redisearch_available()` and `smoke_test()`. It stores
vectors as raw FLOAT32 bytes and creates an HNSW cosine index via `FT.CREATE`.

## How to run Redis Stack (pick one)

**A) Redis Cloud (free tier) — no install, easiest**
1. Create a free database at redis.com (Redis Stack is enabled).
2. Copy the connection URL into `.env`: `REDIS_URL=redis://default:<pass>@<host>:<port>`

**B) Docker** (once Docker Desktop is installed)
```bash
docker run -d -p 6379:6379 redis/redis-stack:latest
# then in .env:  REDIS_URL=redis://localhost:6379/0
```

**C) WSL** (you have WSL)
```bash
# inside WSL
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update && sudo apt-get install -y redis-stack-server
redis-stack-server &
# then in .env (Windows side):  REDIS_URL=redis://localhost:6379/0
```

## Validate the backend
```bash
# with REDIS_URL pointing at Redis Stack:
python -m app.cache.redisearch_store       # runs smoke_test()
```
Expected: `RediSearch smoke test passed.`

## Integration (DONE — behind `VECTOR_BACKEND`)

Already wired: `semantic_cache.py` branches its `store()` and `_nearest()` on
`settings.vector_backend`. Set `VECTOR_BACKEND=redisearch` (with `REDIS_URL` on a Redis Stack
server) and the gateway uses `redisearch_store` (`ensure_index` + `add` + `knn`) instead of
the in-process matrix. Default stays `inproc` so the tested path is unchanged. `/health`
reports the active `vector_backend`.

## Verifying the scaling win (for the report)
Once RediSearch is live, extend `evaluation/latency.py` to also time `redisearch_store.knn()`
at 10k / 100k / 1M vectors, and add that curve to `latency_scaling.png`. That demonstrates the
sub-linear HNSW scaling that the exact in-process index cannot match at very large sizes.
