import numpy as np

from app.cache.policy import CachePolicy
from evaluation.datasets import Pair
from evaluation.stream import replay


def test_replay_populates_only_after_a_miss_and_measures_density() -> None:
    pairs = [
        Pair("alpha one", "alpha one", True, "fixture", "1"),
        Pair("alpha two", "alpha two", True, "fixture", "2"),
    ]
    vectors = {
        "alpha one": np.array([1.0, 0.0], dtype=np.float32),
        "alpha two": np.array([0.99, 0.1], dtype=np.float32),
    }
    result = replay(
        pairs,
        vectors,
        CachePolicy(),
        requests=100,
        seed=7,
        capacity=10,
        ttl_steps=100,
        tenants=1,
        exact=True,
    )
    assert result.upstream_calls >= 1
    assert result.max_resident_entries <= len(pairs)
    assert result.accepted_unknown == 0
    assert result.accepted_known_false == 0
    assert result.intended_retrieval_opportunities > 0


def test_gold_replay_labels_cross_pair_hits_instead_of_unknown() -> None:
    pairs = [
        Pair("who is alpha", "tell me alpha", True, "nq_open", "1"),
        Pair("who is beta", "tell me beta", True, "nq_open", "2"),
    ]
    vectors = {
        query: np.array([1.0, 0.0], dtype=np.float32)
        for pair in pairs
        for query in (pair.stored_query, pair.incoming_query)
    }
    aliases = {
        "who is alpha": frozenset({"alpha"}),
        "tell me alpha": frozenset({"alpha"}),
        "who is beta": frozenset({"beta"}),
        "tell me beta": frozenset({"beta"}),
    }
    result = replay(
        pairs,
        vectors,
        CachePolicy(use_adaptive=False, use_verifier=False, static_threshold=0),
        requests=100,
        seed=7,
        capacity=10,
        ttl_steps=100,
        tenants=1,
        answer_aliases=aliases,
        answers_by_query={
            "who is alpha": "alpha",
            "tell me alpha": "alpha",
            "who is beta": "beta",
            "tell me beta": "beta",
        },
    )
    assert result.accepted_unknown == 0
    assert result.accepted_known_false > 0
    assert result.accepted_known == result.requests - result.upstream_calls


def test_exact_replay_ignores_vector_ties_and_uses_concrete_answer() -> None:
    pairs = [
        Pair("alpha", "alpha", True, "fixture", "1", cached_answer="wrong"),
        Pair("beta", "beta", True, "fixture", "2", cached_answer="beta"),
    ]
    vectors = {query: np.array([1.0, 0.0], dtype=np.float32) for query in ("alpha", "beta")}
    result = replay(
        pairs,
        vectors,
        CachePolicy(),
        requests=100,
        seed=7,
        capacity=10,
        ttl_steps=100,
        tenants=1,
        exact=True,
        answer_aliases={"alpha": frozenset({"alpha"}), "beta": frozenset({"beta"})},
        answers_by_query={"alpha": "wrong", "beta": "beta"},
    )
    assert result.upstream_calls == len(pairs)
    assert result.accepted_known_false > 0
