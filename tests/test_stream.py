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
