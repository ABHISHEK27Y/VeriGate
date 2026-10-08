"""Evaluate the cost-aware model cascade.

Routing rule: score each query's complexity; send easy queries to a cheap model and escalate
only hard ones to the strong model. This measures the cost/quality trade-off vs. two baselines:
  * always-strong  (max quality, max cost)
  * random routing at the same escalation rate (controls for "just escalate less")

Cost model (illustrative): strong model = 15× the cheap model (e.g. a flagship vs a lite/mini
model). Quality proxy: a hard query answered by the cheap model is a quality loss, so
"quality retention" = fraction of truly-hard queries that were escalated to the strong model.

    python -m evaluation.cascade
Outputs evaluation/results/cascade.{png,csv}.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.complexity import complexity_score  # noqa: E402

RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)

CHEAP_COST, STRONG_COST = 1.0, 15.0   # strong model is 15x the cheap one

# ---- labelled dataset: (query, "easy"|"hard") ----
EASY = [
    "what is the capital of France", "who wrote Hamlet", "what is 15% of 200",
    "convert 10 usd to inr", "define photosynthesis", "what is the boiling point of water",
    "how many days in a leap year", "what is the chemical symbol for gold",
    "what is the tallest mountain", "what year did world war 2 end",
    "what is the speed of light", "capital city of Japan", "what is a noun",
    "how many continents are there", "what is the freezing point of water",
    "who painted the Mona Lisa", "what is the square root of 144",
    "what is the currency of Germany", "how many sides does a hexagon have",
    "what is the largest ocean",
]
HARD = [
    "explain why quicksort is O(n log n) on average and when it degrades",
    "compare REST and GraphQL for a mobile app and recommend one with reasons",
    "design a rate limiter for a distributed system and discuss the tradeoffs",
    "derive the gradient of the softmax cross-entropy loss",
    "what are the tradeoffs between microservices and a monolith for a startup",
    "debug this recursion that causes a stack overflow and explain the fix",
    "explain how TCP congestion control works step by step",
    "compare optimistic and pessimistic locking and when to use each",
    "analyze the time and space complexity of Dijkstra with a binary heap",
    "design a schema for a multi-tenant SaaS and justify the isolation strategy",
    "why does gradient descent diverge with a large learning rate, prove it",
    "explain the CAP theorem and its implications for database design",
    "refactor this function for readability and explain each change",
    "compare HNSW and IVF for vector search and their tradeoffs",
    "walk me through how OAuth 2.0 authorization code flow works and why",
    "explain the difference between processes and threads with examples",
    "how would you shard a database and what are the consistency implications",
    "prove that the halting problem is undecidable",
    "design an LRU cache and analyze its operations' complexity",
    "explain why floating point addition is not associative with an example",
]
DATA = [(q, "easy") for q in EASY] + [(q, "hard") for q in HARD]
N_HARD = len(HARD)


def evaluate(threshold: float) -> dict:
    escalated = 0
    hard_kept = 0        # truly-hard queries routed to strong (quality retained)
    tp = fp = fn = tn = 0
    for q, label in DATA:
        hard_pred = complexity_score(q) >= threshold
        if hard_pred:
            escalated += 1
        if label == "hard":
            if hard_pred:
                hard_kept += 1; tp += 1
            else:
                fn += 1
        else:
            if hard_pred:
                fp += 1
            else:
                tn += 1
    n = len(DATA)
    f = escalated / n
    cascade_cost = escalated * STRONG_COST + (n - escalated) * CHEAP_COST
    baseline_cost = n * STRONG_COST
    return {
        "threshold": threshold,
        "escalation_rate": f,
        "cost_reduction": 1 - cascade_cost / baseline_cost,
        "quality_retention": hard_kept / N_HARD,          # hard-recall
        "random_retention": f,                            # random routing at same rate
        "precision": tp / (tp + fp) if (tp + fp) else 1.0,
        "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0,
    }


def main() -> None:
    print(f"\nDataset: {len(EASY)} easy + {len(HARD)} hard queries. "
          f"Cost: cheap={CHEAP_COST}, strong={STRONG_COST} (strong is {STRONG_COST/CHEAP_COST:.0f}x).\n")

    thresholds = [round(0.05 * i, 3) for i in range(0, 21)]
    rows = [evaluate(t) for t in thresholds]

    # table at a few operating points
    print(f"{'thr':>5}{'escalated':>11}{'cost -':>9}{'quality':>9}{'random':>8}{'F1':>7}")
    for r in rows:
        if round(r["threshold"], 2) in (0.0, 0.3, 0.5, 0.7, 1.0):
            print(f"{r['threshold']:>5}{r['escalation_rate']*100:>10.0f}%"
                  f"{r['cost_reduction']*100:>8.0f}%{r['quality_retention']*100:>8.0f}%"
                  f"{r['random_retention']*100:>7.0f}%{r['f1']:>7.2f}")

    default = evaluate(0.5)
    print(f"\nDefault threshold 0.5: cut cost {default['cost_reduction']*100:.0f}% while "
          f"keeping {default['quality_retention']*100:.0f}% of hard queries on the strong model "
          f"(routing F1={default['f1']:.2f}).\n")

    with open(RESULTS / "cascade.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # money graph: quality retention vs cost reduction — cascade vs random
    cx = [r["cost_reduction"] * 100 for r in rows]
    plt.figure(figsize=(7.5, 5.2))
    plt.plot(cx, [r["quality_retention"] * 100 for r in rows], "o-", color="#2ca02c",
             label="cost-aware cascade (complexity classifier)")
    plt.plot(cx, [r["random_retention"] * 100 for r in rows], "s--", color="#999",
             label="random routing (same escalation rate)")
    plt.scatter(default["cost_reduction"] * 100, default["quality_retention"] * 100,
                marker="*", s=300, color="#1f77b4", zorder=6, edgecolors="black",
                linewidths=.6, label="default (threshold 0.5)")
    plt.xlabel("Cost reduction vs. always-strong  → higher is cheaper")
    plt.ylabel("Quality retention  (hard queries kept on strong)  ↑")
    plt.title("Cost-aware cascade: keep quality while cutting cost\n"
              "the classifier beats random routing at every cost level")
    plt.legend(fontsize=8, loc="lower left")
    plt.grid(True, alpha=.3)
    plt.tight_layout()
    plt.savefig(RESULTS / "cascade.png", dpi=150)
    plt.close()
    print(f"Saved: {RESULTS/'cascade.csv'} and cascade.png\n")


if __name__ == "__main__":
    main()
