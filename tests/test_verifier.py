"""Unit tests for the self-verifier (Sub-contribution B), backend-independent.

The lowercase-safe verifier rejects changed content and answer types; the old
capitalization-only behavior remains a named ablation baseline.
"""

from app.cache.policy import CachePolicy
from app.cache.verifier import verify_equivalent


def test_capitalization_baseline_allows_paraphrase_with_few_shared_words():
    ok, reason = verify_equivalent(
        "how do I reset my password",
        "what is the process to recover my account password",
        mode="capitalization",
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
    assert not ok and reason == "content_token_mismatch"


def test_capitalization_baseline_allows_same_entity_paraphrase():
    ok, reason = verify_equivalent(
        "what is the capital of Austria",
        "tell me the capital city of Austria",
        mode="capitalization",
    )
    assert ok, reason


def test_lowercase_content_role_and_answer_type_differences_reject() -> None:
    assert verify_equivalent("capital of austria", "capital of australia") == (
        False,
        "content_token_mismatch",
    )
    assert verify_equivalent("who directed x", "who wrote x") == (False, "role_mismatch")
    assert verify_equivalent("who founded acme", "when was acme founded") == (
        False,
        "answer_type_mismatch",
    )
    assert verify_equivalent(
        "what is the capital of austria", "what is the capital of austria"
    ) == (True, "ok")


def test_old_capitalization_check_remains_explicit_baseline() -> None:
    assert verify_equivalent(
        "capital of austria", "capital of australia", mode="capitalization"
    ) == (True, "ok")


def test_tense_change_rejects_even_when_nouns_match() -> None:
    assert verify_equivalent(
        "who is the president of the club", "who was the president of the club"
    ) == (False, "scope_or_tense_mismatch")


def test_policy_wires_token_diff_as_semantic_default() -> None:
    new = CachePolicy().decide("capital of austria", "capital of australia", 0.99)
    old = CachePolicy(verifier_mode="capitalization").decide(
        "capital of austria", "capital of australia", 0.99
    )
    assert new[0] is False and new[1] == "verify_rejected:content_token_mismatch"
    assert old[0] is True
