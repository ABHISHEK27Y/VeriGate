"""Conservative one-sided risk selection for independent calibration pairs.

For each predeclared threshold, accepted pairs must be IID from the same distribution as
deployment pairs, with independent binary *answer-reuse* labels. Clopper-Pearson bounds
and a Bonferroni correction give a simultaneous confidence statement over the finite
threshold grid. Merely exchangeable or correlated pairs are insufficient for the exact
binomial argument. Distribution shift, label errors and adaptive grid construction break
the guarantee. An empty selected set is always reject-all; it is never reported as zero
measured risk. This module is not enabled by the gateway without reviewed labels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Calibration:
    threshold: float
    accepted: int
    errors: int
    upper_bound: float | None
    epsilon: float
    delta: float


def binomial_upper(errors: int, trials: int, alpha: float) -> float:
    """Exact one-sided Clopper-Pearson upper endpoint P[Bin(n,p) <= errors] = alpha."""
    if trials < 0 or not 0 <= errors <= trials:
        raise ValueError("Require 0 <= errors <= trials")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if trials in (0, errors):
        return 1.0
    lower, upper = 0.0, 1.0
    for _ in range(64):
        middle = (lower + upper) / 2
        if middle == 1.0:
            cdf = 0.0
        else:
            # Log-space CDF avoids underflow for thousands of calibration pairs.
            terms = [
                math.lgamma(trials + 1)
                - math.lgamma(count + 1)
                - math.lgamma(trials - count + 1)
                + count * math.log(middle)
                + (trials - count) * math.log1p(-middle)
                for count in range(errors + 1)
            ]
            largest = max(terms)
            cdf = math.exp(largest) * sum(math.exp(term - largest) for term in terms)
        if cdf > alpha:
            lower = middle
        else:
            upper = middle
    return upper


def select_threshold(
    scores: list[float],
    reusable: list[bool],
    thresholds: list[float],
    *,
    epsilon: float,
    delta: float,
) -> Calibration:
    """Choose least restrictive certified threshold, or reject all with +inf.

    The grid must be fixed independently of calibration labels. `reusable` must label
    the actual cached answer, not query paraphrase similarity.
    """
    if not scores or len(scores) != len(reusable):
        raise ValueError("Nonempty aligned calibration scores and labels required")
    if not thresholds or any(not math.isfinite(t) for t in thresholds):
        raise ValueError("A finite predeclared threshold grid is required")
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("Scores must be finite")
    if not 0.0 <= epsilon < 1.0 or not 0.0 < delta < 1.0:
        raise ValueError("Require epsilon in [0,1), delta in (0,1)")
    grid = sorted(set(thresholds))
    alpha = delta / len(grid)
    for threshold in grid:
        selected = [
            label for score, label in zip(scores, reusable, strict=True) if score >= threshold
        ]
        if not selected:
            continue
        errors = sum(not label for label in selected)
        bound = binomial_upper(errors, len(selected), alpha)
        if bound <= epsilon:
            return Calibration(threshold, len(selected), errors, bound, epsilon, delta)
    return Calibration(math.inf, 0, 0, None, epsilon, delta)
