"""Bounded live candidate selection preserves safety when nearest is unsuitable."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.cache import redisearch_store as rs
from app.cache import storage
from app.cache.semantic_cache import SemanticCache
from app.config import _runtime, get_settings
from app.identity import tenant_id
from evaluation.live_policy_replay import ReplayRow, replay_rows

ARTIFACT = Path(__file__).resolve().parents[1] / "app/cache/artifacts/answer_policy_v1.json"
TENANT = tenant_id("demo-key-123")
SECOND_CANDIDATE = 2


class AlwaysEntails:
    def entail_prob(self, _premise: str, _hypothesis: str) -> float:
        return 0.99


async def set_candidates(cache: SemanticCache, entries: list[tuple[str, str, float]]) -> None:
    token = _runtime.set(cache_config(cache))
    try:
        ranked = []
        for query, answer, similarity in entries:
            await cache.store(query, answer, TENANT)
            if get_settings().vector_backend == "redisearch":
                async with rs._client() as redis_client:
                    _, _, prefix = storage.keys(TENANT, namespace=rs._namespace())
                    ids = await redis_client.smembers(f"{rs._namespace()}:ids:{TENANT}")
                    candidates = [prefix + eid.decode() for eid in ids]
                    keys = [
                        key
                        for key in candidates
                        if (await redis_client.hget(key, "query")) == query.encode()
                    ]
                assert len(keys) == 1
                ranked.append(({"key": keys[0], "query": query, "answer": answer}, similarity))
            else:
                ids = await cache.redis.smembers(cache._ids_key(TENANT))
                eid = None
                for candidate_id in ids:
                    raw = await cache.redis.hget(cache._entry_key(TENANT, candidate_id), "query")
                    if raw == query:
                        eid = candidate_id
                        break
                assert eid is not None
                ranked.append(({"id": eid, "query": query, "answer": answer}, similarity))

        async def fixed_ranked(_vector, _tenant):
            assert _tenant == TENANT
            return ranked, 0.0

        cache._ranked = fixed_ranked
    finally:
        _runtime.reset(token)


def cache_config(cache: SemanticCache):
    return cache._test_config


def test_later_valid_candidate_wins(client) -> None:
    cache = client.app.state.semantic_cache
    cache._test_config = client.app.state.config
    cache._policy.verifier = AlwaysEntails()
    client.portal.call(
        set_candidates,
        cache,
        [
            ("Who wrote the song Silver Valley?", "Wrong", 0.95),
            ("Who wrote the song Silver River?", "Right", 0.91),
        ],
    )
    response = client.post(
        "/v1/chat",
        json={"prompt": "Name the writer of the song Silver River."},
        headers={"x-api-key": "demo-key-123"},
    ).json()
    assert response["cache"] == "HIT"
    assert response["answer"] == "Right"
    assert response["candidate_count"] == SECOND_CANDIDATE
    assert response["selected_rank"] == SECOND_CANDIDATE
    replayed = client.portal.call(
        replay_rows,
        cache,
        TENANT,
        [ReplayRow("Name the writer of the song Silver River.")],
        client.app.state.config,
    )[0]
    assert replayed.status == response["cache"]
    assert replayed.answer == response["answer"]
    assert replayed.selected_rank == response["selected_rank"]


test_later_valid_candidate_wins.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
}


def test_conflicting_accepted_answers_abstain(client) -> None:
    cache = client.app.state.semantic_cache
    cache._test_config = client.app.state.config
    cache._policy.verifier = AlwaysEntails()
    client.portal.call(
        set_candidates,
        cache,
        [
            ("Who wrote the song Silver River?", "Alice", 0.95),
            ("Name the writer of the song Silver River?", "Bob", 0.91),
        ],
    )
    response = client.post(
        "/v1/chat",
        json={"prompt": "Identify the writer of the song Silver River."},
        headers={"x-api-key": "demo-key-123"},
    ).json()
    assert response["cache"] == "MISS"
    assert response["note"] == "conflicting_accepted_answers"
    assert response["provider"] == "mock"


test_conflicting_accepted_answers_abstain.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
}


def test_verification_budget_timeout_is_a_miss(client) -> None:
    cache = client.app.state.semantic_cache
    cache._test_config = client.app.state.config
    cache._policy.verifier = AlwaysEntails()
    client.portal.call(set_candidates, cache, [("Who wrote the song Silver River?", "Alice", 0.95)])
    original = cache._infer

    async def slow_policy(function, *args):
        if function == cache._answer_policy.decide:
            await asyncio.sleep(0.05)
        return await original(function, *args)

    cache._infer = slow_policy
    response = client.post(
        "/v1/chat",
        json={"prompt": "Name the writer of the song Silver River."},
        headers={"x-api-key": "demo-key-123"},
    ).json()
    assert response["cache"] == "MISS"
    assert response["note"] == "verification_budget_exhausted"


test_verification_budget_timeout_is_a_miss.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
    "semantic_verify_budget_ms": 1,
}


def test_all_candidates_invalid_calls_provider(client) -> None:
    cache = client.app.state.semantic_cache
    cache._test_config = client.app.state.config
    cache._policy.verifier = AlwaysEntails()
    client.portal.call(
        set_candidates,
        cache,
        [
            ("Who wrote the song Silver Valley?", "Wrong", 0.95),
            ("Who wrote the song Silver Desert?", "Also wrong", 0.91),
        ],
    )
    response = client.post(
        "/v1/chat",
        json={"prompt": "Name the writer of the song Silver River."},
        headers={"x-api-key": "demo-key-123"},
    ).json()
    assert response["cache"] == "MISS"
    assert response["provider"] == "mock"
    assert response["candidate_count"] == SECOND_CANDIDATE


test_all_candidates_invalid_calls_provider.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
}


def test_unchecked_high_similarity_candidate_forces_abstention(client) -> None:
    cache = client.app.state.semantic_cache
    cache._test_config = client.app.state.config
    cache._policy.verifier = AlwaysEntails()
    client.portal.call(
        set_candidates,
        cache,
        [
            ("Who wrote the song Silver River?", "Alice", 0.95),
            ("Name the writer of the song Silver River?", "Bob", 0.91),
        ],
    )
    response = client.post(
        "/v1/chat",
        json={"prompt": "Identify the writer of the song Silver River."},
        headers={"x-api-key": "demo-key-123"},
    ).json()
    assert response["cache"] == "MISS"
    assert response["note"] == "verification_limit_exhausted"


test_unchecked_high_similarity_candidate_forces_abstention.config_overrides = {
    "cache_match_mode": "semantic",
    "answer_policy_artifact": str(ARTIFACT),
    "semantic_verify_limit": 1,
}
