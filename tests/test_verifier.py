"""Unit tests for the self-verifier (Sub-contribution B), backend-independent.

Locks in the key design decision: reject entity/number/negation mismatches, but ALLOW
genuine paraphrases that share few words.
"""
from app.cache.verifier import verify_equivalent


def test_allows_paraphrase_with_few_shared_words():
    ok, reason = verify_equivalent(
        "how do I reset my password",
        "what is the process to recover my account password",
    )
    assert ok, reason


def test_rejects_number_mismatch():
    ok, reason = verify_equivalent("cost of the 5 gb plan", "cost of the 50 gb plan")
    assert not ok and reason == "number_mismatch"


def test_rejects_negation_mismatch():
    ok, reason = verify_equivalent("is this medicine safe", "is this medicine not safe")
    assert not ok and reason == "negation_mismatch"


def test_rejects_entity_mismatch():
    ok, reason = verify_equivalent(
        "what is the capital of Austria", "what is the capital of Australia"
    )
    assert not ok and reason == "entity_mismatch"


def test_allows_same_entity_paraphrase():
    ok, reason = verify_equivalent(
        "what is the capital of Austria", "tell me the capital city of Austria"
    )
    assert ok, reason
