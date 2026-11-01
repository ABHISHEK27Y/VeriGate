"""Candidate-pair evaluation with explicit denominators and grouped bootstrap intervals."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Decision:
    label: bool
    score: float
    accepted: bool
    group: str


def auroc(rows: list[Decision]) -> float | None:
    positive_count = sum(r.label for r in rows)
    negative_count = len(rows) - positive_count
    if not positive_count or not negative_count:
        return None
    ranked = sorted(rows, key=lambda row: row.score)
    wins, negatives_below = 0.0, 0
    index = 0
    while index < len(ranked):
        end = index + 1
        while end < len(ranked) and ranked[end].score == ranked[index].score:
            end += 1
        positive_tied = sum(row.label for row in ranked[index:end])
        negative_tied = end - index - positive_tied
        wins += positive_tied * (negatives_below + 0.5 * negative_tied)
        negatives_below += negative_tied
        index = end
    return wins / (positive_count * negative_count)


def metrics(rows: list[Decision]) -> dict[str, float | int | None]:
    if not rows:
        raise ValueError("No decisions")
    if any(not math.isfinite(r.score) for r in rows):
        raise ValueError("Scores must be finite")
    positive = sum(r.label for r in rows)
    negative = len(rows) - positive
    accepted = sum(r.accepted for r in rows)
    true = sum(r.label and r.accepted for r in rows)
    false = accepted - true
    return {
        "n": len(rows),
        "accepted": accepted,
        "true_accepts": true,
        "false_accepts": false,
        "coverage": accepted / len(rows),
        "false_hit_among_served": false / accepted if accepted else None,
        "precision": true / accepted if accepted else None,
        "recall": true / positive if positive else None,
        "false_accept_among_negative": false / negative if negative else None,
        "auroc": auroc(rows),
    }


def bootstrap_ci(
    rows: list[Decision], field: str, *, seed: int = 42, resamples: int = 200
) -> tuple[float | None, float | None]:
    """Resample whole source groups; undefined statistics remain undefined."""
    if resamples < 1:
        raise ValueError("At least one resample is required")
    groups: dict[str, list[Decision]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(row.group or f"row:{index}", []).append(row)
    if not groups:
        raise ValueError("No decisions")
    population = list(groups.values())
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        sample = [row for _ in population for row in rng.choice(population)]
        value: float | int | None
        if field == "coverage":
            value = sum(row.accepted for row in sample) / len(sample)
        elif field == "false_hit_among_served":
            accepted = sum(row.accepted for row in sample)
            value = (
                sum(row.accepted and not row.label for row in sample) / accepted
                if accepted
                else None
            )
        elif field == "precision":
            accepted = sum(row.accepted for row in sample)
            value = (
                sum(row.accepted and row.label for row in sample) / accepted if accepted else None
            )
        else:
            value = metrics(sample)[field]
        if isinstance(value, float | int):
            values.append(float(value))
    if not values:
        return None, None
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]


def paired_family_bootstrap(
    families: list[str],
    arm_a: dict[str, tuple[int, int]],
    arm_b: dict[str, tuple[int, int]],
    *,
    seed: int = 42,
    resamples: int = 2000,
) -> dict[str, float | int | None]:
    """Bootstrap the paired difference rate_a - rate_b over the SAME resampled families.

    ``arm_a``/``arm_b`` map each family id to (numerator, denominator) for one arm.
    Because both arms ran the identical frozen families, each resample draws one set
    of families and applies it to both arms, so the between-family variance cancels.
    Returns the point difference and a 95% percentile interval. Overlap or exclusion
    of zero is reported, not interpreted; this does not establish significance on its
    own and says nothing about authored-label error.
    """
    if not families:
        raise ValueError("No families")
    if set(families) - arm_a.keys() or set(families) - arm_b.keys():
        raise ValueError("Both arms must cover every family")
    if resamples < 1:
        raise ValueError("At least one resample is required")

    def rate(arm: dict[str, tuple[int, int]], chosen: list[str]) -> float | None:
        numerator = sum(arm[f][0] for f in chosen)
        denominator = sum(arm[f][1] for f in chosen)
        return numerator / denominator if denominator else None

    point_a, point_b = rate(arm_a, families), rate(arm_b, families)
    point = point_a - point_b if point_a is not None and point_b is not None else None
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(resamples):
        chosen = [rng.choice(families) for _ in families]
        a, b = rate(arm_a, chosen), rate(arm_b, chosen)
        if a is not None and b is not None:
            diffs.append(a - b)
    if not diffs:
        return {"difference": point, "ci_low": None, "ci_high": None, "families": len(families)}
    diffs.sort()
    return {
        "difference": point,
        "ci_low": diffs[int(0.025 * (len(diffs) - 1))],
        "ci_high": diffs[int(0.975 * (len(diffs) - 1))],
        "families": len(families),
        "resamples": len(diffs),
    }


def risk_coverage(rows: list[Decision]) -> list[dict[str, float | None]]:
    """Sweep unique score cutoffs, including reject-all and accept-all endpoints."""
    if not rows:
        raise ValueError("No decisions")
    thresholds = [math.inf, *sorted({r.score for r in rows}, reverse=True), -math.inf]
    curve = []
    for cutoff in thresholds:
        selected = [Decision(r.label, r.score, r.score >= cutoff, r.group) for r in rows]
        result = metrics(selected)
        curve.append(
            {
                "threshold": cutoff,
                "coverage": result["coverage"],
                "risk": result["false_hit_among_served"],
            }
        )
    return curve
