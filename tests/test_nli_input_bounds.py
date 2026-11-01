"""NLI scores only complete paired inputs within the pinned model window."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.cache.verifier import ModelHealth, NliVerifier, pair_digest, verifier_scope

WINDOW = 12
OVER_WINDOW = 13
HIGH_ENTAILMENT = 0.9
TWO_SCOPES = 2
SHA256_HEX_LEN = 64


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
    assert result.score == pytest.approx(float(np.exp(4) / (1 + np.exp(4))))
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


def test_too_long_is_memoized_by_hash_without_retokenizing() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    over = ("one two three four five", "six seven eight nine ten")
    first = verifier.assess(*over)
    assert first.status == "too_long"
    tokenizations = len(verifier.model.tokenizer.calls)
    second = verifier.assess(*over)
    assert second.status == "too_long"
    assert second.input_tokens == OVER_WINDOW
    # No re-tokenization and no prediction on the memoized repeat.
    assert len(verifier.model.tokenizer.calls) == tokenizations
    assert verifier.model.predict_calls == 0
    # Only a hashed key is retained; no raw oversized text.
    (scope, digest), count = next(iter(verifier._too_long.items()))
    assert len(digest) == SHA256_HEX_LEN
    assert "one two three four five" not in digest
    assert count == OVER_WINDOW
    assert digest == pair_digest(*over)


def test_too_long_memo_is_purged_per_scope() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    over = ("one two three four five", "six seven eight nine ten")
    for scope in ("private-alice", "private-bob"):
        token = verifier_scope.set(scope)
        try:
            verifier.assess(*over)
        finally:
            verifier_scope.reset(token)
    verifier.purge_scope("private-alice")
    assert all(key[0] != "private-alice" for key in verifier._too_long)
    assert any(key[0] == "private-bob" for key in verifier._too_long)


def test_model_health_transient_recovers_permanent_sticks() -> None:
    health = ModelHealth(cooldown_sec=1000)
    assert not health.unavailable
    # A transient error (download/import/OOM) is recoverable after cooldown.
    health.record_failure(RuntimeError("model download timed out"))
    assert health.unavailable
    assert health.last_failure_category == "RuntimeError"
    health.record_success()
    assert not health.unavailable
    assert health.last_failure_category is None
    # A config/contract violation is permanent and a later success does not clear it.
    health.record_failure(ValueError("NLI model has no finite input length"))
    assert health.unavailable
    health.record_success()
    assert health.unavailable
    # Only an explicit force clears a permanent failure.
    health.force_unavailable(False)
    assert not health.unavailable


def test_transient_cooldown_blocks_then_allows_retry() -> None:
    health = ModelHealth(cooldown_sec=0.0)
    health.record_failure(OSError("cache dir missing"))
    # A zero cooldown means the very next attempt may retry (no permanent latch).
    assert not health.unavailable
    assert not health.permanent


def test_verifier_recovers_after_forced_then_cleared_unavailable() -> None:
    verifier = NliVerifier()
    verifier.model = PairModel()
    verifier.unavailable = True
    assert verifier.assess("one two", "three four").status == "unavailable"
    verifier.unavailable = False
    assert verifier.assess("one two", "three four").status == "ok"
