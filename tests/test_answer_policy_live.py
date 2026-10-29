"""The same answer policy governs gateway misses and chronological replay hits."""

from pathlib import Path

import pytest

from app.cache.answer_policy import AnswerPolicy
from app.cache.policy import CachePolicy
from app.config import _runtime
from app.embeddings import Embedder
from app.identity import tenant_id
from evaluation.datasets import Pair
from evaluation.stream import replay

ARTIFACT = (
    Path(__file__).resolve().parents[1] / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
)
EXPECTED_REUSES = 2


class ControlledVerifier:
    def entail_prob(self, premise: str, hypothesis: str) -> float:
        return 0.01 if "Germany" in hypothesis else 0.99


def test_invalid_artifact_cannot_be_loaded(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text(ARTIFACT.read_text(encoding="utf-8").replace("0.9", "0.1"))
    with pytest.raises(ValueError, match="Invalid answer-policy artifact"):
        AnswerPolicy.load(path)


def test_answer_decisions_cover_valid_invalid_ambiguous_and_conflict() -> None:
    policy = AnswerPolicy.load(ARTIFACT)
    verifier = ControlledVerifier()
    stored = "What is the capital of France?"
    assert (
        policy.decide("Name France's capital city.", stored, "Paris", 0.8, verifier).action
        == "ACCEPT"
    )
    assert (
        policy.decide("What is the capital of Germany?", stored, "Paris", 0.8, verifier).action
        == "REJECT"
    )
    assert (
        policy.decide(
            "Is the answer to 'What is the capital of France?' Berlin?",
            stored,
            "Paris",
            0.8,
            verifier,
        ).reason
        == "answer_type_mismatch"
    )
    assert (
        policy.decide(
            "Name the capital of Congo.",
            "What is the capital of Congo?",
            "Brazzaville",
            0.8,
            verifier,
        ).action
        == "VERIFY"
    )


def test_live_gateway_and_replay_accept_same_valid_answer(client) -> None:
    stored = "What is the capital of France?"
    incoming = "Name France's capital city."
    answer = "Paris"
    cache = client.app.state.semantic_cache
    cache._policy.verifier = ControlledVerifier()
    tenant = tenant_id("demo-key-123")
    async def seed() -> None:
        token = _runtime.set(client.app.state.config)
        try:
            await cache.store(stored, answer, tenant)
        finally:
            _runtime.reset(token)

    client.portal.call(seed)
    live = client.post(
        "/v1/chat", json={"prompt": incoming}, headers={"x-api-key": "demo-key-123"}
    ).json()
    assert live["cache"] == "HIT", live
    assert live["answer"] == answer
    assert live["note"].startswith("answer_accept:")

    embedder = Embedder()
    vectors = {q: embedder.embed(q) for q in (stored, incoming)}
    pair = Pair(
        stored, incoming, True, "controlled", "france", cached_answer=answer, answer_reusable=True
    )
    result = replay(
        [pair],
        vectors,
        CachePolicy(),
        requests=3,
        seed=11,
        capacity=5,
        ttl_steps=10,
        tenants=1,
        answer_policy=AnswerPolicy.load(ARTIFACT),
        answer_verifier=ControlledVerifier(),
        answer_aliases={stored: frozenset({"paris"}), incoming: frozenset({"paris"})},
        answers_by_query={stored: answer, incoming: answer},
    )
    assert result.accepted_known == EXPECTED_REUSES
    assert result.accepted_known_false == 0


test_live_gateway_and_replay_accept_same_valid_answer.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
}
