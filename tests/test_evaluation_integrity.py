"""Protect the distinction between candidate-pair metrics and workload outcomes."""

# ruff: noqa: PLR2004 - small explicit denominators are the assertion itself

import math

import pytest

from app.cache.policy import CachePolicy
from evaluation.run import pair_metrics


def test_no_accepts_does_not_report_perfect_precision():
    metrics = pair_metrics(tp=0, fp=0, positive_count=15, negative_count=15)
    assert metrics["precision"] is None
    assert metrics["false_reuse_fraction"] is None
    assert metrics["positive_recall"] == 0
    assert metrics["negative_false_accept_rate"] == 0
    assert metrics["acceptance_rate"] == 0


def test_metric_denominators_are_distinct():
    metrics = pair_metrics(tp=3, fp=2, positive_count=10, negative_count=20)
    assert metrics["positive_recall"] == 3 / 10
    assert metrics["negative_false_accept_rate"] == 2 / 20
    assert metrics["false_reuse_fraction"] == 2 / 5
    assert metrics["acceptance_rate"] == 5 / 30


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf, 2.0])
def test_invalid_similarity_fails_closed(score):
    accepted, reason, _ = CachePolicy(use_verifier=False).decide("q", "q", score)
    assert not accepted and reason == "invalid_similarity"


@pytest.mark.parametrize("density", [math.nan, math.inf, -0.1, 1.1])
def test_invalid_density_fails_closed(density):
    accepted, reason, _ = CachePolicy(use_verifier=False).decide("q", "q", 0.99, density)
    assert not accepted and reason == "invalid_density"
