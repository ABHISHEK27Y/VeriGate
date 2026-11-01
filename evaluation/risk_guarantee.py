"""Exercise finite-grid risk selection on synthetic IID data and public pair proxies.

The synthetic study tests the bound's mechanics. Public QQP/PAWS labels are not cached-
answer labels, so neither plot establishes a deployed answer-error guarantee.
"""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.cache.risk import select_threshold  # noqa: E402
from app.embeddings import cosine  # noqa: E402
from evaluation.datasets import Pair, group_split, paws, qqp  # noqa: E402
from evaluation.reproduce import ROOT, SEEDS, _vector_cache  # noqa: E402

TARGETS = (0.005, 0.01, 0.02, 0.05)
GRID = tuple(round(0.5 + 0.05 * i, 2) for i in range(10))
DELTA = 0.05


def _synthetic_run(seed: int, epsilon: float) -> dict[str, Any]:
    rng = random.Random(seed)
    calibration_scores = [rng.random() for _ in range(5000)]
    # Known score-dependent conditional error: P(error | score=s) = .1(1-s).
    calibration_labels = [rng.random() >= 0.1 * (1 - score) for score in calibration_scores]
    selected = select_threshold(
        calibration_scores, calibration_labels, list(GRID), epsilon=epsilon, delta=DELTA
    )
    test_scores = [rng.random() for _ in range(2000)]
    test_labels = [rng.random() >= 0.1 * (1 - score) for score in test_scores]
    accepted = [
        label
        for score, label in zip(test_scores, test_labels, strict=True)
        if score >= selected.threshold
    ]
    true_risk = 0.05 * (1 - selected.threshold) if math.isfinite(selected.threshold) else None
    return {
        "seed": seed,
        "epsilon": epsilon,
        "threshold": selected.threshold,
        "calibration_accepted": selected.accepted,
        "bound": selected.upper_bound,
        "true_conditional_risk": true_risk,
        "test_accepted": len(accepted),
        "observed_test_risk": sum(not label for label in accepted) / len(accepted)
        if accepted
        else None,
        "test_coverage": len(accepted) / len(test_scores),
        "true_risk_exceeds_target": int(true_risk > epsilon) if true_risk is not None else None,
    }


def _score(pairs: list[Pair], vectors: dict[str, np.ndarray]) -> list[float]:
    return [cosine(vectors[p.stored_query], vectors[p.incoming_query]) for p in pairs]


def _shift_rows() -> list[dict[str, Any]]:
    qqp_rows = qqp(ROOT / "data" / "qqp.tsv")
    paws_rows = paws(ROOT / "data" / "paws.tsv")
    random.Random(42).shuffle(qqp_rows)
    qqp_rows = qqp_rows[:2000]
    paws_rows = paws_rows[:2000]
    qqp_vectors, paws_vectors = _vector_cache(qqp_rows), _vector_cache(paws_rows)
    paws_scores = _score(paws_rows, paws_vectors)
    output = []
    for seed in SEEDS:
        parts = group_split(qqp_rows, seed)
        calibration = parts["cal"]
        test = parts["test"]
        scores = _score(calibration, qqp_vectors)
        qqp_test_scores = _score(test, qqp_vectors)
        for epsilon in TARGETS:
            selected = select_threshold(
                scores,
                [pair.equivalent for pair in calibration],
                list(GRID),
                epsilon=epsilon,
                delta=DELTA,
            )
            for source, rows, check_scores in (
                ("qqp", test, qqp_test_scores),
                ("paws_shift", paws_rows, paws_scores),
            ):
                accepted = [
                    pair.equivalent
                    for pair, score in zip(rows, check_scores, strict=True)
                    if score >= selected.threshold
                ]
                output.append(
                    {
                        "seed": seed,
                        "epsilon": epsilon,
                        "threshold": selected.threshold,
                        "source": source,
                        "calibration_accepted": selected.accepted,
                        "bound": selected.upper_bound,
                        "test_accepted": len(accepted),
                        "observed_pair_proxy_risk": (
                            sum(not label for label in accepted) / len(accepted)
                            if accepted
                            else None
                        ),
                        "coverage": len(accepted) / len(rows),
                    }
                )
    return output


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    results = ROOT / "evaluation" / "results"
    synthetic = [_synthetic_run(seed, epsilon) for seed in range(50) for epsilon in TARGETS]
    shifted = _shift_rows()
    _write_csv(results / "risk_synthetic.csv", synthetic)
    _write_csv(results / "risk_shift_proxy.csv", shifted)
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for epsilon in TARGETS:
        rows = [row for row in synthetic if row["epsilon"] == epsilon]
        certified = [row for row in rows if row["true_conditional_risk"] is not None]
        mean_true = (
            sum(float(row["true_conditional_risk"]) for row in certified) / len(certified)
            if certified
            else 0.0
        )
        mean_coverage = sum(float(row["test_coverage"]) for row in rows) / len(rows)
        axes[0].scatter(epsilon, mean_true, color="#1f77b4")
        axes[1].scatter(epsilon, mean_coverage, color="#2ca02c")
    axes[0].plot(TARGETS, TARGETS, "--", color="gray", label="target")
    axes[0].set(xlabel="Target risk", ylabel="Mean true risk (synthetic IID)")
    axes[0].legend()
    axes[1].set(xlabel="Target risk", ylabel="Mean test coverage (synthetic IID)")
    fig.suptitle("Risk selection mechanics; not an answer-cache guarantee")
    fig.tight_layout()
    fig.savefig(results / "risk_synthetic.png", dpi=150)
    plt.close(fig)
    print("Generated synthetic risk study and QQP-to-PAWS pair-proxy shift CSV.")


if __name__ == "__main__":
    main()
