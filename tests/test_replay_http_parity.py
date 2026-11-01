"""Retrieval replay matches HTTP cache decisions where admission is held fixed."""

from __future__ import annotations

from app.identity import tenant_id
from evaluation.live_policy_replay import ReplayRow, replay_rows


def test_chronological_exact_http_and_retrieval_replay(client) -> None:
    prompt = "Explain retry backoff."
    headers = {"x-api-key": "demo-key-123"}
    first = client.post("/v1/chat", headers=headers, json={"prompt": prompt}).json()
    second = client.post("/v1/chat", headers=headers, json={"prompt": prompt}).json()
    assert [first["cache"], second["cache"]] == ["MISS", "HIT"]
    cache = client.app.state.semantic_cache
    tenant = tenant_id("demo-key-123")
    client.portal.call(cache.clear, tenant)
    replayed = client.portal.call(
        replay_rows,
        cache,
        tenant,
        [ReplayRow(prompt, first["answer"]), ReplayRow(prompt)],
        client.app.state.config,
    )
    assert [(row.status, row.reason) for row in replayed] == [
        (first["cache"], first["note"]),
        (second["cache"], second["note"]),
    ]
