"""The same answer policy governs gateway misses and chronological replay hits."""

from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pytest

from app.cache import redisearch_store as rs
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
REDISEARCH_NEIGHBORS = 5


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


@pytest.mark.parametrize("score", [1.0, 1.000000238418579])
def test_float32_cosine_rounding_keeps_valid_exact_answer(score: float) -> None:
    policy = AnswerPolicy.load(ARTIFACT)
    result = policy.decide(
        "Who wrote Hamlet?", "Who wrote Hamlet?", "Shakespeare", score, ControlledVerifier()
    )
    assert result.action == "ACCEPT"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), 1.01, -1.01])
def test_invalid_cosine_still_rejected(score: float) -> None:
    policy = AnswerPolicy.load(ARTIFACT)
    result = policy.decide(
        "Who wrote Hamlet?", "Who wrote Hamlet?", "Shakespeare", score, ControlledVerifier()
    )
    assert result.action == "REJECT"
    assert result.reason == "invalid_candidate"


def test_long_context_abstains_before_nli() -> None:
    class NoModelVerifier:
        def entail_prob(self, _premise: str, _hypothesis: str) -> float:
            raise AssertionError("NLI should not see truncated context")

    query = "Explain the unusual historical record " + "detail " * 90
    result = AnswerPolicy.load(ARTIFACT).decide(query, query, "the archive", 0.9, NoModelVerifier())
    assert result.action == "VERIFY"
    assert result.reason == "context_too_long"


def test_answer_mentioned_in_incoming_question_abstains_on_role_reversal() -> None:
    policy = AnswerPolicy.load(ARTIFACT)
    result = policy.decide(
        "Who did Bob marry?", "Who did Alice marry?", "Bob", 0.9, ControlledVerifier()
    )
    assert result.action == "VERIFY"
    assert result.reason == "answer_mentioned_in_question"


def test_changed_scope_abstains_without_nli() -> None:
    policy = AnswerPolicy.load(ARTIFACT)
    result = policy.decide(
        "When did the team reach the final?",
        "When was the last year the team reached the final?",
        "2018",
        0.9,
        ControlledVerifier(),
    )
    assert result.action == "VERIFY"
    assert result.reason == "scope_changed"


def test_scope_and_answer_guards_allow_unaffected_paraphrase() -> None:
    result = AnswerPolicy.load(ARTIFACT).decide(
        "Name the capital city of France.",
        "What is France's capital?",
        "Paris",
        0.9,
        ControlledVerifier(),
    )
    assert result.action == "ACCEPT"


def test_answer_mentioned_in_exact_repeat_does_not_force_abstention() -> None:
    question = "Who did Bob marry?"
    result = AnswerPolicy.load(ARTIFACT).decide(
        question, question, "Bob", 1.0, ControlledVerifier()
    )
    assert result.action == "ACCEPT"


@pytest.mark.parametrize(
    ("incoming", "stored", "answer", "reason"),
    [
        (
            "who does betty end up with on riverdale",
            "does archie end up with betty or veronica in riverdale",
            "Betty",
            "answer_mentioned_in_question",
        ),
        (
            "when did the eagles play in the superbowl",
            "when was the last year the eagles went to the superbowl",
            "following the 2017 season",
            "scope_changed",
        ),
    ],
)
def test_close_neighbor_suspicious_cases_abstain(
    incoming: str, stored: str, answer: str, reason: str
) -> None:
    result = AnswerPolicy.load(ARTIFACT).decide(
        incoming, stored, answer, 0.95, ControlledVerifier()
    )
    assert result.action == "VERIFY"
    assert result.reason == reason


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


def test_changed_inproc_answer_after_policy_decision_calls_provider(client) -> None:
    stored = "What is the capital of France?"
    incoming = "Name France's capital city."
    cache = client.app.state.semantic_cache
    cache._policy.verifier = ControlledVerifier()
    tenant = tenant_id("demo-key-123")

    async def seed_and_patch() -> None:
        token = _runtime.set(client.app.state.config)
        try:
            await cache.store(stored, "Paris", tenant)
            original_infer = cache._infer

            async def mutate_after_decision(function, *args):
                result = await original_infer(function, *args)
                if function == cache._answer_policy.decide:
                    ids = await cache.redis.smembers(cache._ids_key(tenant))
                    eid = next(iter(ids))
                    await cache.redis.hset(cache._entry_key(tenant, eid), "answer", "Berlin")
                return result

            cache._infer = mutate_after_decision
        finally:
            _runtime.reset(token)

    client.portal.call(seed_and_patch)
    response = client.post(
        "/v1/chat", json={"prompt": incoming}, headers={"x-api-key": "demo-key-123"}
    ).json()
    assert response["cache"] == "MISS", response
    assert response["answer"] != "Berlin"
    assert response["provider"] == "mock"


test_changed_inproc_answer_after_policy_decision_calls_provider.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
    "vector_backend": "inproc",
}


def test_changed_redisearch_answer_after_policy_decision_is_miss(client, monkeypatch) -> None:
    cache = client.app.state.semantic_cache
    cache._policy.verifier = ControlledVerifier()
    tenant = tenant_id("demo-key-123")
    stored = "What is the capital of France?"
    incoming = "Name France's capital city."
    key = f"test:rs:entry:{tenant}:candidate"

    async def fake_knn(_vec, _tenant, k=5, *, include_key=False):
        assert include_key and k == REDISEARCH_NEIGHBORS
        return [(stored, "Paris", 0.8, key)]

    async def changed_candidate(_key, _tenant):
        assert _key == key and _tenant == tenant
        return {"query": stored, "answer": "Berlin"}

    monkeypatch.setattr(rs, "knn", fake_knn)
    monkeypatch.setattr(rs, "read_candidate", changed_candidate)

    async def lookup():
        token = _runtime.set(
            client.app.state.config.model_copy(update={"vector_backend": "redisearch"})
        )
        try:
            return await cache.lookup(incoming, tenant)
        finally:
            _runtime.reset(token)

    result = client.portal.call(lookup)
    assert result.status == "MISS"
    assert result.reason == "candidate_changed"


test_changed_redisearch_answer_after_policy_decision_is_miss.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
}


@pytest.mark.asyncio
async def test_redisearch_discards_hash_changed_after_search(monkeypatch) -> None:
    tenant = "t_test"
    key = f"{rs._namespace()}:entry:{tenant}:one"

    class ChangingRedis:
        async def execute_command(self, *_args):
            return [
                1,
                key.encode(),
                [b"query", b"Which city?", b"answer", b"Paris", b"score", b"0.1"],
            ]

        async def hgetall(self, _key):
            return {b"tenant": tenant.encode(), b"query": b"Which city?", b"answer": b"Berlin"}

        async def zadd(self, *_args, **_kwargs):
            raise AssertionError("changed candidate must not be touched")

    @asynccontextmanager
    async def fake_client():
        yield ChangingRedis()

    monkeypatch.setattr(rs, "_client", fake_client)
    hits = await rs.knn(np.array([1.0, 0.0], dtype=np.float32), tenant)
    assert hits == []
