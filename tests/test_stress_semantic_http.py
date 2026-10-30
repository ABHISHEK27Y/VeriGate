"""Integrity checks for the frozen controlled-answer HTTP workload."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from app.cache.semantic_cache import SemanticCache
from app.config import Settings, _runtime
from app.providers.evaluation import ControlledEvaluationProvider
from scripts.analyze_stress_semantic_http import aggregate
from scripts.stress_semantic_http import FAMILIES, REQUESTS, classify, digest

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = ROOT / "evaluation/runs/nq_song_stress_20261030_v1"


def test_frozen_workload_integrity() -> None:
    freeze = json.loads((WORKLOAD / "freeze.json").read_text(encoding="utf-8"))
    assert digest(WORKLOAD / "workload.csv") == freeze["workload_sha256"]
    assert digest(WORKLOAD / "provider_answers.json") == freeze["provider_answers_sha256"]
    # The frozen run was created on Windows; its relative path must resolve on Linux CI too.
    policy_path = Path(freeze["policy_artifact"].replace("\\", "/"))
    assert digest(ROOT / policy_path) == freeze["policy_sha256"]
    with (WORKLOAD / "workload.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == REQUESTS
    assert len({row["id"] for row in rows}) == REQUESTS
    assert len({row["question"] for row in rows}) == REQUESTS
    assert [int(row["position"]) for row in rows] == list(range(1, REQUESTS + 1))
    families = defaultdict(list)
    for row in rows:
        families[row["family_id"]].append(row)
    assert len(families) == FAMILIES
    for family_rows in families.values():
        assert Counter(row["kind"] for row in family_rows) == {
            "original": 1,
            "paraphrase_1": 1,
            "paraphrase_2": 1,
            "paraphrase_3": 1,
            "hard_negative": 1,
        }
        original = next(row for row in family_rows if row["kind"] == "original")
        for row in family_rows:
            if row["kind"] == "hard_negative":
                assert row["reference_answer"] != original["reference_answer"]
                assert row["contrasts_with"] == original["id"]
            else:
                assert row["reference_answer"] == original["reference_answer"]
    distances = [
        int(row["distance_from_previous_family"])
        for row in rows
        if row["distance_from_previous_family"]
    ]
    short, medium = 10, 200
    assert any(distance <= short for distance in distances)
    assert any(short < distance <= medium for distance in distances)
    assert any(distance > medium for distance in distances)
    assert any(
        min(row["position"] for row in group)
        != next(row["position"] for row in group if row["kind"] == "original")
        for group in families.values()
    )


@pytest.mark.asyncio
async def test_controlled_provider_is_prompt_only() -> None:
    path = WORKLOAD / "provider_answers.json"
    question, answer = next(iter(json.loads(path.read_text(encoding="utf-8")).items()))
    provider = ControlledEvaluationProvider(str(path))
    assert [chunk async for chunk in provider.stream(question)] == [answer]
    with pytest.raises(ValueError, match="absent"):
        [chunk async for chunk in provider.stream("unknown")]


def test_outcome_denominators_use_live_entries() -> None:
    row = {"reference_answer": "A"}
    assert classify(row, {"cache": "MISS"}, 200, {}, False) == "cold_miss"
    assert classify(row, {"cache": "MISS"}, 200, {}, True) == "expiry_or_eviction_miss"
    assert classify(row, {"cache": "MISS"}, 200, {"q": "A"}, True) == "retrieval_miss"
    assert (
        classify(row, {"cache": "MISS", "selected_cached_query": "q"}, 200, {"q": "A"}, True)
        == "verifier_false_rejection"
    )
    assert (
        classify(row, {"cache": "MISS", "selected_cached_query": "q"}, 200, {"q": "B"}, True)
        == "expiry_or_eviction_miss"
    )
    assert (
        classify(row, {"cache": "HIT", "answer": "B"}, 200, {"q": "B"}, True)
        == "incorrect_acceptance"
    )


def test_aggregate_reuse_denominator_excludes_cold_miss() -> None:
    base = {
        "http_status": "200",
        "http_latency_ms": "10",
        "gateway_latency_ms": "8",
        "stage_latency_ms": '{"cache_lookup":2,"provider":4}',
        "verifier_invoked": "False",
        "provider_invoked": "True",
    }
    data = [
        {**base, "outcome": "cold_miss", "suitable_answer_present": "False"},
        {**base, "outcome": "retrieval_miss", "suitable_answer_present": "True"},
        {
            **base,
            "outcome": "correct_hit",
            "suitable_answer_present": "True",
            "provider_invoked": "False",
        },
    ]
    result = aggregate(data)
    expected_opportunities = 2
    expected_reuse = 1 / expected_opportunities
    assert result["reuse_opportunities"] == expected_opportunities
    assert result["reuse_per_opportunity"] == expected_reuse
    assert result["unnecessary_provider_calls"] == 1


def test_controlled_provider_is_not_valid_in_production() -> None:
    config = Settings(
        _env_file=None,
        environment="production",
        llm_provider="controlled-eval",
        redis_url="redis://localhost:6379/0",
        api_keys="private-key",
        metrics_token="private-metrics",
        api_key_salt="s" * 32,
    )
    with pytest.raises(ValueError, match="real provider"):
        config.validate_production()


def test_static_baseline_disables_adaptation_and_structural_verifier() -> None:
    config = Settings(
        _env_file=None,
        cache_policy_static=True,
        answer_policy_artifact="",
        embedding_backend="hash",
    )
    token = _runtime.set(config)
    try:
        cache = SemanticCache(redis_client=object(), embedder=object())
        assert cache._policy.use_adaptive is False
        assert cache._policy.use_verifier is False
        assert cache._policy.static_threshold == config.cache_similarity_base
    finally:
        _runtime.reset(token)
