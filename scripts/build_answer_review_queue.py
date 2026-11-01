"""Create a balanced local review queue; never infer answer labels from pair labels."""

from __future__ import annotations

import csv
import random
from pathlib import Path

from evaluation.datasets import Pair, paws, qqp

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIELDS = (
    "source",
    "source_id",
    "family",
    "stored_query",
    "cached_answer",
    "incoming_query",
    "pair_label",
    "answer_reusable",
    "reason",
    "reviewer_1",
    "reviewer_2",
    "review_status",
    "tenant_id",
    "context_version",
    "answer_version",
)


def _sample(pairs: list[Pair], count: int, seed: int) -> list[Pair]:
    rng = random.Random(seed)
    positive = [pair for pair in pairs if pair.equivalent]
    negative = [pair for pair in pairs if not pair.equivalent]
    half = count // 2
    if len(positive) < half or len(negative) < count - half:
        raise ValueError("Insufficient rows for a balanced review queue")
    return rng.sample(positive, half) + rng.sample(negative, count - half)


def main() -> None:
    sources = {"qqp": qqp(DATA / "qqp.tsv"), "paws": paws(DATA / "paws.tsv")}
    selected = [
        pair
        for name, rows in sources.items()
        for pair in _sample(rows, 1000, 42 if name == "qqp" else 43)
    ]
    random.Random(44).shuffle(selected)
    target = DATA / "answer_review.tsv"
    if target.exists():
        raise FileExistsError(f"Preserving existing review work: {target}")
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for pair in selected:
            writer.writerow(
                {
                    "source": pair.source,
                    "source_id": pair.source_id,
                    "family": "",
                    "stored_query": pair.stored_query,
                    "cached_answer": "",
                    "incoming_query": pair.incoming_query,
                    "pair_label": int(pair.equivalent),
                    "answer_reusable": "",
                    "reason": "",
                    "reviewer_1": "",
                    "reviewer_2": "",
                    "review_status": "unreviewed",
                    "tenant_id": "",
                    "context_version": "",
                    "answer_version": "",
                }
            )
    print(f"Created {len(selected)} unreviewed rows: {target}")


if __name__ == "__main__":
    main()
