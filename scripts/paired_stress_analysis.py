"""Matched-family paired difference for a saved stress run's two arms (audit F20).

The stress arms run the identical frozen families, so the static-vs-answer-aware
comparison is paired. The original analyzer reported only each arm's marginal
family-clustered interval, whose overlap settles nothing. This computes the
paired per-family difference (static minus answer-aware) with a 95% interval,
resampling the SAME families for both arms, and writes a NEW file without
touching the historical run.

Run: python -m scripts.paired_stress_analysis evaluation/runs/<run> <arm_a> <arm_b> <out.json>
e.g. ... nq_song_stress_20261030_v3 static_sufficient answer_aware_sufficient \
        evaluation/runs/nq_song_stress_20261030_v3/paired_family_difference.json
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from evaluation.protocol import paired_family_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def _per_family(rows: list[dict], outcome: str) -> dict[str, tuple[int, int]]:
    """(count of `outcome`, total requests) per family id."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        counts[row["family_id"]][0] += row["outcome"] == outcome
        counts[row["family_id"]][1] += 1
    return {family: (pair[0], pair[1]) for family, pair in counts.items()}


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("arm_a")
    parser.add_argument("arm_b")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    run = args.run if args.run.is_absolute() else ROOT / args.run
    rows_a = _load(run / args.arm_a / "requests.csv")
    rows_b = _load(run / args.arm_b / "requests.csv")
    families = sorted({row["family_id"] for row in rows_a})
    if families != sorted({row["family_id"] for row in rows_b}):
        raise ValueError("Arms do not cover the same families")

    result: dict[str, object] = {
        "schema": "paired-family-difference-v1",
        "run": run.relative_to(ROOT).as_posix(),
        "arm_a": args.arm_a,
        "arm_b": args.arm_b,
        "note": (
            "Difference is arm_a - arm_b over the same resampled families. "
            "Not a significance test; says nothing about authored-label error."
        ),
        "metrics": {},
    }
    for label, outcome in (
        ("suspected_incorrect_hits_per_request", "incorrect_acceptance"),
        ("correct_hits_per_request", "correct_hit"),
    ):
        result["metrics"][label] = paired_family_bootstrap(  # type: ignore[index]
            families, _per_family(rows_a, outcome), _per_family(rows_b, outcome)
        )

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
