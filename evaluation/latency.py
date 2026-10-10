"""Latency benchmark — how fast is each stage, and how much does the cache save?

    python -m evaluation.latency

Measures (p50/p95/p99, in milliseconds):
  * embedding a query
  * KNN cache lookup at several cache sizes (shows the O(n) brute-force scaling)
  * Tier-1 verification
  * Tier-2 NLI verification
  * the full cache-HIT path (Tier-1) and (Tier-1 + Tier-2)

Then compares the cache-hit path against a typical hosted-LLM call to quantify the speedup.
Outputs: evaluation/results/latency.csv and latency.png.

Note: uses in-memory fakeredis, so KNN numbers reflect client + parse + cosine cost, not
network I/O. A real Redis + RediSearch KNN would change absolute numbers but the O(n)
scaling shown here is exactly what motivates that upgrade.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import os
import time
from dataclasses import dataclass
from pathlib import Path

os.environ["EMBEDDING_BACKEND"] = "minilm"
os.environ.setdefault("CACHE_MATCH_MODE", "semantic")
os.environ.setdefault("REDIS_URL", "")

import matplotlib  # noqa: E402
import numpy as np  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app import embeddings  # noqa: E402
from app.cache.semantic_cache import SemanticCache  # noqa: E402
from app.cache.verifier import default_verifier, nli_equivalent, verify_equivalent  # noqa: E402
from app.embeddings import embed  # noqa: E402

RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)

# A typical hosted-LLM end-to-end latency, for the speedup comparison (conservative).
LLM_REFERENCE_MS = 800.0


@dataclass(slots=True)
class _LatencyData:
    """Container for all latency measurement data."""

    embed_stats: dict
    knn_latencies: dict
    v1_stats: dict
    v2_stats: dict | None
    hit_lat_t1_stats: dict
    sizes: list[int]


def pct(samples_ms: list[float]) -> dict:
    a = np.array(samples_ms)
    return {
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
        "mean": float(a.mean()),
    }


def time_it(fn, reps: int) -> list[float]:
    out = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return out


async def atime_it(fn, reps: int) -> list[float]:
    out = []
    for _ in range(reps):
        t0 = time.perf_counter()
        result = fn()
        if asyncio.iscoroutine(result):
            await result
        out.append((time.perf_counter() - t0) * 1000.0)
    return out


TENANT = "t_bench"


async def populate(n: int, cache: SemanticCache) -> None:
    """Fill the cache with n distinct entries (batch-embedded for speed)."""
    await cache.clear(TENANT)
    model = embeddings.default_embedder().model  # loaded by the warm-up embed() below
    assert model is not None, "Model should be loaded when backend is minilm"
    queries = [
        f"how do I configure feature number {i} in module {i} of the system" for i in range(n)
    ]
    vecs = model.encode(queries, normalize_embeddings=True, batch_size=64)
    r = cache.redis
    for i, (q, v) in enumerate(zip(queries, vecs, strict=True)):
        eid = f"e{i}"
        await r.hset(
            cache._entry_key(TENANT, eid),
            mapping={
                "query": q,
                "answer": f"answer {i}",
                "vec": cache._vec_to_str(np.asarray(v, dtype=np.float32)),
                "ts": "0",
            },
        )  # type: ignore[misc]
        await r.sadd(cache._ids_key(TENANT), eid)  # type: ignore[misc]
    # Rebuild in-process index
    await cache.reload(TENANT)


async def _measure_speedups(
    embed_stats: dict,
    knn_latencies: dict,
    v1_stats: dict,
    hit_lat_t1_stats: dict,
) -> None:
    """Print speedup comparisons vs LLM reference."""
    for label, lat in [
        ("embed", embed_stats["mean"]),
        ("knn@1000", knn_latencies[1000]["mean"]),
        ("t1", v1_stats["mean"]),
        ("hit_t1", hit_lat_t1_stats["mean"]),
    ]:
        if lat:
            speedup = LLM_REFERENCE_MS / lat
            print(
                f"  {label} mean={lat:.1f}ms -> "
                f"{speedup:.0f}x faster than {LLM_REFERENCE_MS:.0f}ms LLM call"
            )


async def _write_csv(data: _LatencyData) -> None:
    """Write latency results to CSV."""
    with (RESULTS / "latency.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stage", "reps", "p50_ms", "p95_ms", "p99_ms", "mean_ms"])
        w.writerow(
            [
                "embed",
                100,
                data.embed_stats["p50"],
                data.embed_stats["p95"],
                data.embed_stats["p99"],
                data.embed_stats["mean"],
            ]
        )
        for n in data.sizes:
            d = data.knn_latencies[n]
            w.writerow([f"knn_n{n}", 50, d["p50"], d["p95"], d["p99"], d["mean"]])
        w.writerow(
            [
                "tier1_verify",
                100,
                data.v1_stats["p50"],
                data.v1_stats["p95"],
                data.v1_stats["p99"],
                data.v1_stats["mean"],
            ]
        )
        if data.v2_stats:
            w.writerow(
                [
                    "tier2_nli",
                    20,
                    data.v2_stats["p50"],
                    data.v2_stats["p95"],
                    data.v2_stats["p99"],
                    data.v2_stats["mean"],
                ]
            )
        w.writerow(
            [
                "hit_tier1_n1000",
                100,
                data.hit_lat_t1_stats["p50"],
                data.hit_lat_t1_stats["p95"],
                data.hit_lat_t1_stats["p99"],
                data.hit_lat_t1_stats["mean"],
            ]
        )


def _plot_knn_scaling(sizes: list[int], knn_latencies: dict) -> None:
    """Generate KNN scaling plot."""
    plt.figure(figsize=(7, 4))
    x = sizes
    y = [knn_latencies[n]["mean"] for n in sizes]
    plt.plot(x, y, "o-", label="mean")
    y95 = [knn_latencies[n]["p95"] for n in sizes]
    plt.plot(x, y95, "s--", label="p95", alpha=0.7)
    plt.xlabel("Cache size (entries)")
    plt.ylabel("Latency (ms)")
    plt.title("In-process KNN lookup scaling (O(n) brute-force)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(RESULTS / "latency_scaling.png", dpi=150)
    plt.close()


def _plot_stage_breakdown(
    embed_stats: dict,
    knn_latencies: dict,
    v1_stats: dict,
    hit_lat_t1_stats: dict,
) -> None:
    """Generate per-stage latency breakdown plot."""
    stages = ["embed", "knn@1000", "tier1", "hit_t1"]
    means = [
        embed_stats["mean"],
        knn_latencies[1000]["mean"],
        v1_stats["mean"],
        hit_lat_t1_stats["mean"],
    ]
    plt.figure(figsize=(7, 4))
    bars = plt.bar(stages, means, color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"])
    plt.ylabel("Latency (ms)")
    plt.title("Cache-hit path latency breakdown")
    for bar, m in zip(bars, means, strict=True):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.01,
            f"{m:.1f}ms",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    plt.axhline(
        LLM_REFERENCE_MS,
        color="red",
        linestyle="--",
        alpha=0.5,
        label=f"LLM reference ({LLM_REFERENCE_MS:.0f}ms)",
    )
    plt.legend()
    plt.tight_layout()
    plt.savefig(RESULTS / "latency.png", dpi=150)
    plt.close()


async def main() -> None:
    print("Warming up models (embeddings + NLI)...")
    _ = embed("warmup")
    _ = verify_equivalent("warmup", "warmup")
    with contextlib.suppress(Exception):
        _ = nli_equivalent("warmup", "warmup")

    cache = SemanticCache(embedder=embeddings.default_embedder())

    # 1) Embedding latency
    query = "how do I reset my password please"
    embed_lat = time_it(lambda: embed(query), 100)
    embed_stats = pct(embed_lat)
    print(f"\nEmbedding (100 reps): {embed_stats}")

    # 2) KNN lookup scaling
    sizes = [10, 100, 500, 1000, 2000]
    knn_latencies = {}
    for n in sizes:
        await populate(n, cache)
        probe = embed(query)
        lookup_lat = await atime_it(lambda probe=probe: cache._nearest_inproc(probe, TENANT), 50)  # type: ignore[misc]
        knn_latencies[n] = pct(lookup_lat)
        print(f"KNN lookup (n={n:4d}, 50 reps): {knn_latencies[n]}")

    # 3) Verification latency
    v1_lat = time_it(
        lambda: verify_equivalent(
            "how do I reset my password", "what is the process to recover my account password"
        ),
        100,
    )
    v1_stats = pct(v1_lat)
    print(f"\nTier-1 verify (100 reps): {v1_stats}")

    v2_lat = []
    for _ in range(20):
        default_verifier().cache.clear()  # measure inference, not a memoized pair
        t0 = time.perf_counter()
        with contextlib.suppress(Exception):
            nli_equivalent(
                "how do I reset my password", "what is the process to recover my account password"
            )
        v2_lat.append((time.perf_counter() - t0) * 1000.0)
    v2_stats = pct(v2_lat) if v2_lat else None
    if v2_stats:
        print(f"Tier-2 NLI verify (20 reps): {v2_stats}")

    # 4) Full cache-hit path latency
    await populate(1000, cache)

    async def hit_lookup():
        result = await cache.lookup(
            "how do I configure feature number 7 in module 7 of the system", TENANT
        )
        assert result.status == "HIT", f"Expected a measured HIT, got {result}"

    await hit_lookup()  # warm index and model before measuring
    hit_lat_t1 = await atime_it(hit_lookup, 100)
    hit_lat_t1_stats = pct(hit_lat_t1)
    print(f"\nFull HIT path (Tier-1, n=1000, 100 reps): {hit_lat_t1_stats}")

    # 5) Speedup vs LLM reference
    await _measure_speedups(embed_stats, knn_latencies, v1_stats, hit_lat_t1_stats)

    # Write CSV
    latency_data = _LatencyData(
        embed_stats=embed_stats,
        knn_latencies=knn_latencies,
        v1_stats=v1_stats,
        v2_stats=v2_stats,
        hit_lat_t1_stats=hit_lat_t1_stats,
        sizes=sizes,
    )
    await _write_csv(latency_data)

    # Plot 1: KNN scaling
    _plot_knn_scaling(sizes, knn_latencies)

    # Plot 2: Per-stage bars
    _plot_stage_breakdown(embed_stats, knn_latencies, v1_stats, hit_lat_t1_stats)

    print(f"\nSaved: {RESULTS / 'latency.csv'}")
    print(f"Saved: {RESULTS / 'latency.png'} (per-stage bars)")
    print(f"Saved: {RESULTS / 'latency_scaling.png'} (KNN O(n) growth)")
    await cache.redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
