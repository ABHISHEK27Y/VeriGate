import math

import pytest

from app.cache.risk import binomial_upper, select_threshold


def test_exact_upper_bound_zero_errors() -> None:
    trials, alpha = 100, 0.05
    expected = 1 - alpha ** (1 / trials)
    assert binomial_upper(0, trials, alpha) == pytest.approx(expected)


def test_empty_and_all_error_cases() -> None:
    assert binomial_upper(0, 0, 0.05) == 1.0
    assert binomial_upper(5, 5, 0.05) == 1.0
    with pytest.raises(ValueError):
        select_threshold([], [], [0.5], epsilon=0.05, delta=0.05)


def test_zero_target_and_insufficient_sample_reject_all() -> None:
    result = select_threshold([0.9] * 100, [True] * 100, [0.8], epsilon=0, delta=0.05)
    assert math.isinf(result.threshold)
    assert result.upper_bound is None
    assert select_threshold([0.9], [True], [0.8], epsilon=0.05, delta=0.05).accepted == 0


def test_certifies_when_sufficient_clean_calibration_data() -> None:
    count, cutoff, target = 1000, 0.8, 0.01
    result = select_threshold([0.9] * count, [True] * count, [cutoff], epsilon=target, delta=0.05)
    assert result.threshold == cutoff
    assert result.accepted == count
    assert result.upper_bound is not None and result.upper_bound <= target


def test_invalid_scores_and_grid_fail_closed() -> None:
    with pytest.raises(ValueError):
        select_threshold([math.nan], [True], [0.5], epsilon=0.05, delta=0.05)
    with pytest.raises(ValueError):
        select_threshold([0.9], [True], [math.nan], epsilon=0.05, delta=0.05)
