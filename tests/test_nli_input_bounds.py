"""NLI scores only complete paired inputs within the pinned model window."""

from types import SimpleNamespace

import numpy as np

from app.cache.verifier import NliVerifier, verifier_scope

WINDOW = 12
OVER_WINDOW = 13
HIGH_ENTAILMENT = 0.9
TWO_SCOPES = 2


class PairTokenizer:
    model_max_length = WINDOW

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, premise: str, hypothesis: str, **kwargs):
        self.calls.append(kwargs)
        assert kwargs == {"truncation": False, "add_special_tokens": True}
        # Both strings and pair separators count toward the effective window.
        return {"input_ids": list(range(len(premise.split()) + len(hypothesis.split()) + 3))}


class PairModel:
    max_seq_length = WINDOW

    def __init__(self) -> None:
        self.tokenizer = PairTokenizer()
        self.model = SimpleNamespace(
            config=SimpleNamespace(
                max_position_embeddings=WINDOW, id2label={0: "CONTRADICTION", 1: "ENTAILMENT"}
            )
        )
        self.predict_calls = 0

    def predict(self, _pairs):
        self.predict_calls += 1
        return np.asarray([[0.0, 4.0]])


def test_combined_pair_at_boundary_is_scored_without_truncation() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    result = verifier.assess("one two three four", "five six seven eight nine")
    assert result.status == "ok"
    assert result.input_tokens == WINDOW
    assert result.score is not None and result.score > HIGH_ENTAILMENT
    assert verifier.model.predict_calls == 1


def test_one_token_over_combined_limit_abstains_without_prediction() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    result = verifier.assess("one two three four five", "six seven eight nine ten")
    assert result.status == "too_long"
    assert result.input_tokens == OVER_WINDOW
    assert verifier.model.predict_calls == 0
    assert not verifier.unavailable


def test_long_pair_does_not_poison_next_short_pair() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    assert verifier.entail_prob("one " * 20, "two " * 20) is None
    assert verifier.assess("one two", "three four").status == "ok"
    assert verifier.model.predict_calls == 1


def test_nli_memoization_is_partitioned_by_authorized_cache_scope() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    for scope in ("private-alice", "private-alice", "workspace-engineering"):
        token = verifier_scope.set(scope)
        try:
            assert verifier.assess("one two", "three four").status == "ok"
        finally:
            verifier_scope.reset(token)
    assert verifier.model.predict_calls == TWO_SCOPES


def test_purge_scope_removes_only_its_memoized_assertions() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    for scope in ("private-alice", "private-bob"):
        token = verifier_scope.set(scope)
        try:
            verifier.assess("one two", "three four")
        finally:
            verifier_scope.reset(token)
    verifier.purge_scope("private-alice")
    assert all(key[0] != "private-alice" for key in verifier.cache)
    assert any(key[0] == "private-bob" for key in verifier.cache)
