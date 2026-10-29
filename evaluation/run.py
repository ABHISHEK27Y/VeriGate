"""Run the evaluation and produce the results (tables, CSV, and figures).

    python -m evaluation.run          # from the project root

Forces the real 'minilm' embeddings so scores are meaningful. Outputs go to
evaluation/results/ :  metrics.csv, tradeoff.png (the money graph), ablation.png.
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from pathlib import Path

os.environ["EMBEDDING_BACKEND"] = "minilm"  # real semantic embeddings for evaluation
os.environ.setdefault("REDIS_URL", "")  # no server needed; eval works on pairs

import matplotlib  # noqa: E402

matplotlib.use("Agg")  # headless: save PNGs, no window
import matplotlib.pyplot as plt  # noqa: E402

from app.cache.policy import CachePolicy  # noqa: E402
from app.cache.volatility import is_volatile  # noqa: E402
from app.embeddings import cosine, embed  # noqa: E402
from evaluation import benchmark  # noqa: E402

RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)

# ---- embed every query once ----
_VECS: dict[str, object] = {}


def vec(q: str):
    if q not in _VECS:
        _VECS[q] = embed(q)
    return _VECS[q]


def pair_is_hit(policy: CachePolicy, stored_q: str, new_q: str) -> bool:
    """Would `policy` serve stored_q's answer for new_q?"""
    sim = cosine(vec(new_q), vec(stored_q))
    hit, _reason, _t = policy.decide(new_q, stored_q, sim, density=0.0)
    return hit


def pair_metrics(tp: int, fp: int, positive_count: int, negative_count: int) -> dict:
    """Describe candidate-pair decisions; these are not workload hit or savings rates."""
    if positive_count <= 0 or negative_count <= 0:
        raise ValueError("Both classes must contain examples")
    if not 0 <= tp <= positive_count or not 0 <= fp <= negative_count:
        raise ValueError("Accepted counts must lie within their class sizes")
    accepted = tp + fp
    fn = positive_count - tp
    return {
        "positive_recall": tp / positive_count,
        "negative_false_accept_rate": fp / negative_count,
        "acceptance_rate": accepted / (positive_count + negative_count),
        "false_reuse_fraction": fp / accepted if accepted else None,
        "precision": tp / accepted if accepted else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0,
        "true_accepts": tp,
        "false_accepts": fp,
        "accepted": accepted,
        "positive_count": positive_count,
        "negative_count": negative_count,
    }


def evaluate(policy: CachePolicy) -> dict:
    tp = sum(pair_is_hit(policy, a, b) for a, b in benchmark.POSITIVES)
    fp = sum(pair_is_hit(policy, a, b) for a, b in benchmark.NEGATIVES)
    metrics = pair_metrics(tp, fp, len(benchmark.POSITIVES), len(benchmark.NEGATIVES))
    metrics["model_status"] = (
        "unavailable" if policy.use_nli and policy.verifier.unavailable else "available"
    )
    return metrics


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
    "Baseline (static T=0.72)": CachePolicy(
        use_adaptive=False, use_verifier=False, static_threshold=0.72
    ),
    "+ Adaptive T": CachePolicy(use_adaptive=True, use_verifier=False),
    "+ Verifier (Tier-1)": CachePolicy(
        use_adaptive=False, use_verifier=True, static_threshold=0.72
    ),
    "VeriGate (Tier-1)": CachePolicy(use_adaptive=True, use_verifier=True),
}


def _print_ablation_table() -> list[dict]:
    """Print ablation table and return rows for CSV."""
    rows = []
    print(f"{'System':<26}{'pos recall':>11}{'neg accept':>12}{'precision':>11}{'F1':>7}")
    print("-" * 65)
    for name, pol in SYSTEMS.items():
        m = evaluate(pol)
        rows.append({"system": name, **m})
        precision_text = f"{m['precision'] * 100:.1f}%" if m["precision"] is not None else "N/A"
        if m["model_status"] == "unavailable":
            precision_text = "N/A"
        print(
            f"{name:<26}{m['positive_recall'] * 100:>10.1f}%"
            f"{m['negative_false_accept_rate'] * 100:>11.1f}%"
            f"{precision_text:>11}"
            f"{m['f1']:>7.2f}"
        )
    print()
    if any(row["model_status"] == "unavailable" for row in rows):
        print("NLI model unavailable: that row is a fail-closed run, not an NLI quality result.\n")
    return rows


def _print_false_hits_by_group() -> None:
    """Print false hits by negative type."""
    print("False hits by negative type (lower is better):")
    header = "  ".join(f"{g:>13}" for g in benchmark.NEGATIVE_GROUPS)
    print(f"{'System':<26}{header}")
    for name, pol in SYSTEMS.items():
        g = false_hits_by_group(pol)
        cells = "  ".join(f"{g[k]:>13}" for k in benchmark.NEGATIVE_GROUPS)
        print(f"{name:<26}{cells}")
    print()


def _print_volatility_results() -> None:
    """Print volatility detector results."""
    v = evaluate_volatility()
    print(
        f"Staleness detector: recall {v['recall']} on volatile queries, "
        f"false positives {v['false_positives']} on stable controls.\n"
    )


def _write_metrics_csv(rows: list[dict]) -> None:
    """Write metrics to CSV."""
    with (RESULTS / "metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "system",
                "positive_recall",
                "negative_false_accept_rate",
                "acceptance_rate",
                "false_reuse_fraction",
                "precision",
                "f1",
                "true_accepts",
                "false_accepts",
                "accepted",
                "positive_count",
                "negative_count",
                "model_status",
            ],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(rows)


@dataclass(slots=True)
class _TradeoffData:
    """Container for tradeoff plot data."""

    base_fx: list
    base_hy: list
    veri_fx: list
    veri_hy: list
    nli_fx: list
    nli_hy: list
    full: dict


def _compute_sweep_curves(*, with_nli: bool = False) -> _TradeoffData:
    """Compute sweep curves for tradeoff plot."""
    sweep_t = [round(0.45 + 0.025 * i, 3) for i in range(21)]  # 0.45 .. 0.95

    def sweep(use_verifier: bool, use_nli: bool = False):
        pts = [
            evaluate(
                CachePolicy(
                    use_adaptive=False,
                    use_verifier=use_verifier,
                    use_nli=use_nli,
                    static_threshold=t,
                )
            )
            for t in sweep_t
        ]
        return [p["negative_false_accept_rate"] for p in pts], [p["positive_recall"] for p in pts]

    base_fx, base_hy = sweep(False)
    veri_fx, veri_hy = sweep(True)
    nli_ready = with_nli and not SYSTEMS["VeriGate (Tier-1+2 NLI)"].verifier.unavailable
    nli_fx, nli_hy = sweep(True, use_nli=True) if nli_ready else ([], [])
    full = evaluate(SYSTEMS["VeriGate (Tier-1)"])  # recommended default config
    return _TradeoffData(
        base_fx=base_fx,
        base_hy=base_hy,
        veri_fx=veri_fx,
        veri_hy=veri_hy,
        nli_fx=nli_fx,
        nli_hy=nli_hy,
        full=full,
    )


def _plot_tradeoff(data: _TradeoffData) -> None:
    """Generate tradeoff plot."""
    plt.figure(figsize=(7.5, 5.5))
    plt.plot(
        data.base_fx,
        data.base_hy,
        "o-",
        color="#d62728",
        alpha=0.8,
        label="Static-threshold baseline (T swept)",
    )
    plt.plot(
        data.veri_fx,
        data.veri_hy,
        "s-",
        color="#1f77b4",
        alpha=0.8,
        label="+ Tier-1 verifier (T swept)",
    )
    if data.nli_fx:
        plt.plot(
            data.nli_fx,
            data.nli_hy,
            "^-",
            color="#9467bd",
            alpha=0.8,
            label="+ Tier-1 & Tier-2 NLI (T swept)",
        )
    plt.scatter(
        data.full["negative_false_accept_rate"],
        data.full["positive_recall"],
        marker="*",
        s=320,
        color="#2ca02c",
        zorder=6,
        edgecolors="black",
        linewidths=0.6,
        label="VeriGate default (adaptive + Tier-1)",
    )
    plt.xlabel("False acceptance among negative pairs   ← lower is better")
    plt.ylabel("Recall among positive pairs   ↑ higher is better")
    plt.title("Candidate-pair acceptance on the small smoke fixture")
    plt.legend(fontsize=8, loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.xlim(left=-0.02)
    plt.tight_layout()
    plt.savefig(RESULTS / "tradeoff.png", dpi=150)
    plt.close()


def _plot_ablation() -> None:
    """Generate ablation bar chart."""
    names = list(SYSTEMS)
    hits = [evaluate(SYSTEMS[n])["positive_recall"] * 100 for n in names]
    falses = [evaluate(SYSTEMS[n])["negative_false_accept_rate"] * 100 for n in names]
    x = range(len(names))
    plt.figure(figsize=(8, 5))
    plt.bar([i - 0.2 for i in x], hits, width=0.4, label="positive recall %", color="#2ca02c")
    plt.bar([i + 0.2 for i in x], falses, width=0.4, label="negative acceptance %", color="#d62728")
    plt.xticks(list(x), names, rotation=15, ha="right", fontsize=8)
    plt.ylabel("percent")
    plt.title("Ablation: contribution of each component")
    plt.legend()
    plt.tight_layout()
    plt.savefig(RESULTS / "ablation.png", dpi=150)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-nli", action="store_true", help="run optional local NLI model")
    args = parser.parse_args()
    if args.with_nli:
        SYSTEMS["VeriGate (Tier-1+2 NLI)"] = CachePolicy(
            use_adaptive=True, use_verifier=True, use_nli=True
        )
    print(
        f"\nBenchmark: {len(benchmark.POSITIVES)} positive pairs, "
        f"{len(benchmark.NEGATIVES)} hard-negative pairs, "
        f"{len(benchmark.VOLATILE)} volatile queries.\n"
    )

    # 1) Ablation table
    rows = _print_ablation_table()

    # false hits by failure mode (shows which component catches what)
    _print_false_hits_by_group()

    # volatility results
    _print_volatility_results()

    # 2) write CSV
    _write_metrics_csv(rows)

    # 3) the money graph: sweep the threshold for BOTH systems (verifier off vs on)
    #    so the two trade-off curves can be compared directly.
    tradeoff_data = _compute_sweep_curves(with_nli=args.with_nli)
    _plot_tradeoff(tradeoff_data)

    # 4) ablation bar chart
    _plot_ablation()

    print(f"Saved: {RESULTS / 'metrics.csv'}")
    print(f"Saved: {RESULTS / 'tradeoff.png'}   (the money graph)")
    print(f"Saved: {RESULTS / 'ablation.png'}\n")


if __name__ == "__main__":
    main()
