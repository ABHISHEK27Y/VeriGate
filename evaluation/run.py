"""Run the evaluation and produce the results (tables, CSV, and figures).

    python -m evaluation.run          # from the project root

Forces the real 'minilm' embeddings so scores are meaningful. Outputs go to
evaluation/results/ :  metrics.csv, tradeoff.png (the money graph), ablation.png.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

os.environ["EMBEDDING_BACKEND"] = "minilm"   # real semantic embeddings for evaluation
os.environ.setdefault("REDIS_URL", "")        # no server needed; eval works on pairs

import matplotlib                              # noqa: E402
matplotlib.use("Agg")                          # headless: save PNGs, no window
import matplotlib.pyplot as plt                # noqa: E402

from app.cache.policy import CachePolicy       # noqa: E402
from app.cache.volatility import is_volatile   # noqa: E402
from app.embeddings import cosine, embed       # noqa: E402
from evaluation import benchmark               # noqa: E402

RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)

# ---- embed every query once ----
_VECS: dict[str, "object"] = {}


def vec(q: str):
    if q not in _VECS:
        _VECS[q] = embed(q)
    return _VECS[q]


def pair_is_hit(policy: CachePolicy, stored_q: str, new_q: str) -> bool:
    """Would `policy` serve stored_q's answer for new_q?"""
    sim = cosine(vec(new_q), vec(stored_q))
    hit, _reason, _t = policy.decide(new_q, stored_q, sim, density=0.0)
    return hit


def evaluate(policy: CachePolicy) -> dict:
    tp = sum(pair_is_hit(policy, a, b) for a, b in benchmark.POSITIVES)
    fp = sum(pair_is_hit(policy, a, b) for a, b in benchmark.NEGATIVES)
    P, N = len(benchmark.POSITIVES), len(benchmark.NEGATIVES)
    fn, tn = P - tp, N - fp
    hit_rate = tp / P
    false_hit_rate = fp / N
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
    return {
        "hit_rate": hit_rate,
        "false_hit_rate": false_hit_rate,
        "precision": precision,
        "f1": f1,
        "true_hits": tp,
        "false_hits": fp,
    }


def false_hits_by_group(policy: CachePolicy) -> dict[str, str]:
    out = {}
    for name, pairs in benchmark.NEGATIVE_GROUPS.items():
        fp = sum(pair_is_hit(policy, a, b) for a, b in pairs)
        out[name] = f"{fp}/{len(pairs)}"
    return out


def evaluate_volatility() -> dict:
    detected = sum(is_volatile(q) for q in benchmark.VOLATILE)
    false_pos = sum(is_volatile(q) for q in benchmark.STABLE_CONTROLS)
    return {
        "recall": f"{detected}/{len(benchmark.VOLATILE)}",
        "false_positives": f"{false_pos}/{len(benchmark.STABLE_CONTROLS)}",
    }


# ---- the systems we compare (the ablation) ----
SYSTEMS = {
    "Baseline (static T=0.72)": CachePolicy(use_adaptive=False, use_verifier=False,
                                            static_threshold=0.72),
    "+ Adaptive T": CachePolicy(use_adaptive=True, use_verifier=False),
    "+ Verifier (Tier-1)": CachePolicy(use_adaptive=False, use_verifier=True,
                                       static_threshold=0.72),
    "VeriGate (Tier-1)": CachePolicy(use_adaptive=True, use_verifier=True),
    "VeriGate (Tier-1+2 NLI)": CachePolicy(use_adaptive=True, use_verifier=True,
                                           use_nli=True),
}


def main() -> None:
    print(f"\nBenchmark: {len(benchmark.POSITIVES)} positive pairs, "
          f"{len(benchmark.NEGATIVES)} hard-negative pairs, "
          f"{len(benchmark.VOLATILE)} volatile queries.\n")

    # 1) Ablation table
    rows = []
    print(f"{'System':<26}{'hit-rate':>10}{'false-hit':>11}{'precision':>11}{'F1':>7}")
    print("-" * 65)
    for name, pol in SYSTEMS.items():
        m = evaluate(pol)
        rows.append({"system": name, **m})
        print(f"{name:<26}{m['hit_rate']*100:>9.1f}%{m['false_hit_rate']*100:>10.1f}%"
              f"{m['precision']*100:>10.1f}%{m['f1']:>7.2f}")
    print()

    # false hits by failure mode (shows which component catches what)
    print("False hits by negative type (lower is better):")
    header = "  ".join(f"{g:>13}" for g in benchmark.NEGATIVE_GROUPS)
    print(f"{'System':<26}{header}")
    for name, pol in SYSTEMS.items():
        g = false_hits_by_group(pol)
        cells = "  ".join(f"{g[k]:>13}" for k in benchmark.NEGATIVE_GROUPS)
        print(f"{name:<26}{cells}")
    print()

    v = evaluate_volatility()
    print(f"Staleness detector: recall {v['recall']} on volatile queries, "
          f"false positives {v['false_positives']} on stable controls.\n")

    # 2) write CSV
    with open(RESULTS / "metrics.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["system", "hit_rate", "false_hit_rate",
                                          "precision", "f1", "true_hits", "false_hits"])
        w.writeheader()
        w.writerows(rows)

    # 3) the money graph: sweep the threshold for BOTH systems (verifier off vs on)
    #    so the two trade-off curves can be compared directly.
    sweep_t = [round(0.45 + 0.025 * i, 3) for i in range(21)]  # 0.45 .. 0.95

    def sweep(use_verifier: bool, use_nli: bool = False):
        pts = [evaluate(CachePolicy(use_adaptive=False, use_verifier=use_verifier,
                                    use_nli=use_nli, static_threshold=t))
               for t in sweep_t]
        return [p["false_hit_rate"] for p in pts], [p["hit_rate"] for p in pts]

    base_fx, base_hy = sweep(False)
    veri_fx, veri_hy = sweep(True)
    nli_fx, nli_hy = sweep(True, use_nli=True)
    full = evaluate(SYSTEMS["VeriGate (Tier-1)"])  # recommended default config

    plt.figure(figsize=(7.5, 5.5))
    plt.plot(base_fx, base_hy, "o-", color="#d62728", alpha=0.8,
             label="Static-threshold baseline (T swept)")
    plt.plot(veri_fx, veri_hy, "s-", color="#1f77b4", alpha=0.8,
             label="+ Tier-1 verifier (T swept)")
    plt.plot(nli_fx, nli_hy, "^-", color="#9467bd", alpha=0.8,
             label="+ Tier-1 & Tier-2 NLI (T swept)")
    plt.scatter(full["false_hit_rate"], full["hit_rate"], marker="*", s=320,
                color="#2ca02c", zorder=6, edgecolors="black", linewidths=0.6,
                label="VeriGate default (adaptive + Tier-1)")
    plt.xlabel("False-hit rate  (wrong answers served)   ← lower is better")
    plt.ylabel("Hit rate  (cost savings)   ↑ higher is better")
    plt.title("A correctness–savings spectrum\n"
              "each verifier tier pushes the curve left (fewer wrong answers)")
    plt.legend(fontsize=8, loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.xlim(left=-0.02)
    plt.tight_layout()
    plt.savefig(RESULTS / "tradeoff.png", dpi=150)
    plt.close()

    # 4) ablation bar chart
    names = list(SYSTEMS)
    hits = [evaluate(SYSTEMS[n])["hit_rate"] * 100 for n in names]
    falses = [evaluate(SYSTEMS[n])["false_hit_rate"] * 100 for n in names]
    x = range(len(names))
    plt.figure(figsize=(8, 5))
    plt.bar([i - 0.2 for i in x], hits, width=0.4, label="hit-rate %", color="#2ca02c")
    plt.bar([i + 0.2 for i in x], falses, width=0.4, label="false-hit %", color="#d62728")
    plt.xticks(list(x), names, rotation=15, ha="right", fontsize=8)
    plt.ylabel("percent")
    plt.title("Ablation: contribution of each component")
    plt.legend()
    plt.tight_layout()
    plt.savefig(RESULTS / "ablation.png", dpi=150)
    plt.close()

    print(f"Saved: {RESULTS/'metrics.csv'}")
    print(f"Saved: {RESULTS/'tradeoff.png'}   (the money graph)")
    print(f"Saved: {RESULTS/'ablation.png'}\n")


if __name__ == "__main__":
    main()
