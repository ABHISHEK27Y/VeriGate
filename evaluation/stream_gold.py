"""Replay a filling cache with oracle NQ gold-answer-match labels for every hit."""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.cache.policy import CachePolicy  # noqa: E402
from app.embeddings import active_backend  # noqa: E402
from evaluation.gold_answers import load_pairs  # noqa: E402
from evaluation.reproduce import ROOT, _vector_cache  # noqa: E402
from evaluation.stream import replay  # noqa: E402


def run(target: Path | None = None) -> Path:
    pairs, aliases = load_pairs(ROOT / "data" / "answer_pairs_directional.tsv")
    vectors = _vector_cache(pairs)
    # Synthetic upstream: stored-side answer is the mined concrete text; on the
    # incoming side a deterministic reference string stands in for a provider reply.
    answers_by_query = {
        pair.stored_query: pair.cached_answer for pair in pairs if pair.cached_answer is not None
    }
    for pair in pairs:
        answers_by_query.setdefault(pair.incoming_query, sorted(aliases[pair.incoming_query])[0])
    rows = []
    for capacity in (10, 100):
        for name, policy, exact in (
            ("exact", CachePolicy(), True),
            ("static_0.72", CachePolicy(use_adaptive=False, use_verifier=False), False),
            ("adaptive_tier1", CachePolicy(), False),
        ):
            result = replay(
                pairs,
                vectors,
                policy,
                requests=1500,
                seed=11,
                capacity=capacity,
                ttl_steps=500,
                answer_aliases=aliases,
                answers_by_query=answers_by_query,
                exact=exact,
            )
            rows.append(
                {
                    "capacity_per_tenant": capacity,
                    "system": name,
                    **asdict(result),
                    "label_type": "cached_answer_reference_match_replay",
                    "embedding_backend": active_backend(),
                }
            )
    if target is None:
        target = ROOT / "evaluation" / "results" / f"directional_stream_{active_backend()}.csv"
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for name in ("exact", "static_0.72", "adaptive_tier1"):
        subset = [row for row in rows if row["system"] == name]
        capacities = [row["capacity_per_tenant"] for row in subset]
        axes[0].plot(
            capacities,
            [row["accepted_known"] / row["requests"] for row in subset],
            marker="o",
            label=name,
        )
        axes[1].plot(
            capacities,
            [
                row["accepted_known_false"] / row["accepted_known"]
                if row["accepted_known"]
                else 0.0
                for row in subset
            ],
            marker="o",
            label=name,
        )
    axes[0].set(xlabel="Per-tenant capacity", ylabel="Accepted requests / requests")
    axes[1].set(xlabel="Per-tenant capacity", ylabel="Gold-mismatch / accepted")
    fig.suptitle("NQ concrete-reference replay; not generated-answer correctness")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(target.with_suffix(".png"), dpi=150)
    plt.close(fig)
    print(target)
    return target


if __name__ == "__main__":
    run()
