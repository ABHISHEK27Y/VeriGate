"""Compare KNN lookup latency: in-process vectorised index vs. RediSearch (HNSW).

Requires a live Redis Stack. Run:
    REDIS_URL=redis://localhost:6379/0 EMBEDDING_BACKEND=minilm \
    python -m evaluation.backend_compare

Populates both backends with the same vectors at several sizes and times a KNN lookup on
each. Saves evaluation/results/backend_compare.{png,csv}.
"""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

os.environ.setdefault("EMBEDDING_BACKEND", "minilm")

import numpy as np                              # noqa: E402
import matplotlib                               # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                 # noqa: E402

from app import embeddings                      # noqa: E402
from app.cache import redisearch_store as rs    # noqa: E402
from app.cache import semantic_cache as sc      # noqa: E402
from app.embeddings import embed                # noqa: E402

RESULTS = Path(__file__).parent / "results"
SIZES = [1000, 5000, 10000]
REPS = 100


def p50(fn, reps=REPS):
    xs = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000.0)
    return float(np.percentile(xs, 50))


def main():
    if not rs.redisearch_available():
        raise SystemExit("Redis Stack not reachable. Set REDIS_URL to a Redis Stack server.")

    print(f"\nEmbedding {max(SIZES)} queries once (batch)...")
    embed("warm up")
    model = embeddings._model
    queries = [f"how do I configure feature number {i} in module {i}" for i in range(max(SIZES))]
    vecs = model.encode(queries, normalize_embeddings=True, batch_size=128).astype(np.float32)

    probe = embed("what are the steps to set up feature number 7 in module 7")

    # reset RediSearch index
    from app.redis_client import get_redis
    os.environ["REDIS_URL"]  # ensure present
    get_redis().flushall()

    TEN = "t_bench"
    rows = []
    added = 0
    for n in SIZES:
        # ---- in-process: set the tenant's matrix directly to the first n vectors ----
        sc._INDEX[TEN] = {
            "ids": [f"e{i}" for i in range(n)], "queries": queries[:n],
            "answers": [f"answer {i}" for i in range(n)], "mat": vecs[:n].copy(), "built": True,
        }
        t_inproc = p50(lambda: sc._nearest_inproc(probe, TEN))

        # ---- redisearch: add up to n ----
        rs.ensure_index(vecs.shape[1])
        for i in range(added, n):
            rs.add(queries[i], f"answer {i}", vecs[i], TEN)
        added = n
        t_redis = p50(lambda: rs.knn(probe, TEN, k=1))

        rows.append((n, t_inproc, t_redis))
        print(f"  n={n:<6}  in-process {t_inproc:7.3f} ms   redisearch {t_redis:7.3f} ms")

    with open(RESULTS / "backend_compare.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cache_size", "inproc_p50_ms", "redisearch_p50_ms"])
        w.writerows(rows)

    ns = [r[0] for r in rows]
    plt.figure(figsize=(7, 4.5))
    plt.plot(ns, [r[1] for r in rows], "o-", color="#2ca02c", label="in-process (NumPy matmul)")
    plt.plot(ns, [r[2] for r in rows], "s-", color="#1f77b4", label="RediSearch (HNSW, shared)")
    plt.xlabel("cache entries")
    plt.ylabel("KNN lookup p50 (ms)")
    plt.title("KNN backend comparison: in-process vs. RediSearch")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(RESULTS / "backend_compare.png", dpi=150)
    plt.close()
    print(f"\nSaved: {RESULTS/'backend_compare.csv'} and backend_compare.png\n")


if __name__ == "__main__":
    main()
