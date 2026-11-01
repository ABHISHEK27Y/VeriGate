"""Provider terminal metadata must gate cache writes through the HTTP gateway."""

from __future__ import annotations

import json
from http import HTTPStatus

import httpx

from app.providers.openai_compat import OpenAICompatibleProvider
from app.providers.registry import ProviderRegistry

HEADERS = {"x-api-key": "demo-key-123"}


def upstream(client, events: list[dict | str]) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer isolated-test-key"
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert (
            payload["max_completion_tokens"]
            == client.app.state.config.provider_max_completion_tokens
        )
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            text="\n\n".join(
                f"data: {event if isinstance(event, str) else json.dumps(event)}"
                for event in events
            )
            + "\n\n",
        )

    provider = OpenAICompatibleProvider(
        "openai-isolated",
        "isolated-test-key",
        "https://example.invalid/v1",
        "test-model",
        family="openai",
    )
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client.app.state.provider_registry = ProviderRegistry(
        providers=(provider,), redis=client.app.state.redis
    )


def content(text: str) -> dict:
    return {"model": "returned-model", "choices": [{"delta": {"content": text}}]}


def finish(reason: str) -> dict:
    return {"choices": [{"delta": {}, "finish_reason": reason}]}


def test_complete_answer_and_usage_only_event_are_cached(client) -> None:
    upstream(
        client,
        [
            content("A complete answer."),
            finish("stop"),
            {
                "choices": [],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
            },
            "[DONE]",
        ],
    )
    body = {"prompt": "Explain HTTP status codes"}
    first = client.post("/v1/chat", headers=HEADERS, json=body)
    assert first.status_code == HTTPStatus.OK
    assert first.json()["cache"] == "MISS"
    assert first.json()["storage_outcome"] == "stored"
    assert first.json()["finish_reason"] == "stop"
    assert first.json()["provider_model"] == "returned-model"
    assert first.json()["provider_usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 4,
        "total_tokens": 11,
    }
    assert client.post("/v1/chat", headers=HEADERS, json=body).json()["cache"] == "HIT"


def test_length_filtered_and_missing_finish_are_never_cached(client) -> None:
    for reason in ("length", "content_filter", None):
        events = [content("An incomplete answer.")]
        if reason is not None:
            events.append(finish(reason))
        events.append("[DONE]")
        upstream(client, events)
        response = client.post(
            "/v1/chat",
            headers=HEADERS,
            json={"prompt": f"Explain provider finish {reason}"},
        )
        assert response.status_code == HTTPStatus.BAD_GATEWAY
        assert response.json()["detail"] == "upstream unavailable"


def test_malformed_answer_and_tool_output_fail_stream_without_cache(client) -> None:
    for bad in ("{malformed", {"choices": [{"delta": {"tool_calls": [{}]}}]}):
        upstream(client, [content("Partial."), bad, finish("stop"), "[DONE]"])
        prompt = f"Explain malformed output {type(bad).__name__}"
        response = client.post("/v1/chat/stream", headers=HEADERS, json={"prompt": prompt})
        assert response.status_code == HTTPStatus.OK
        assert "event: error" in response.text
        assert "data: [DONE]" not in response.text
        upstream(client, [content("Recovered."), finish("stop"), "[DONE]"])
        retry = client.post("/v1/chat", headers=HEADERS, json={"prompt": prompt})
        assert retry.json()["cache"] == "MISS"


def test_terminal_event_cannot_be_revised_or_followed_by_content(client) -> None:
    invalid = (
        ("length_then_stop", [content("Partial."), finish("length"), finish("stop"), "[DONE]"]),
        ("stop_then_content", [content("Partial."), finish("stop"), content("Late."), "[DONE]"]),
        ("duplicate_stop", [content("Partial."), finish("stop"), finish("stop"), "[DONE]"]),
        (
            "error_with_usage",
            [
                content("Partial."),
                finish("stop"),
                {"error": {"message": "failed"}, "usage": {"total_tokens": 2}},
                "[DONE]",
            ],
        ),
    )
    for name, events in invalid:
        upstream(client, events)
        prompt = f"Explain terminal event {name}"
        json_response = client.post("/v1/chat", headers=HEADERS, json={"prompt": prompt})
        assert json_response.status_code == HTTPStatus.BAD_GATEWAY, name
        stream_response = client.post("/v1/chat/stream", headers=HEADERS, json={"prompt": prompt})
        assert "event: error" in stream_response.text, name
        assert "data: [DONE]" not in stream_response.text, name
        upstream(client, [content("Recovered."), finish("stop"), "[DONE]"])
        retry = client.post("/v1/chat", headers=HEADERS, json={"prompt": prompt})
        assert retry.json()["cache"] == "MISS", name


test_terminal_event_cannot_be_revised_or_followed_by_content.config_overrides = {
    "rate_limit_capacity": 20,
}


def test_stream_accepts_usage_after_normal_terminal(client) -> None:
    upstream(
        client,
        [
            content("Complete."),
            finish("stop"),
            {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3}},
            "[DONE]",
        ],
    )
    response = client.post(
        "/v1/chat/stream", headers=HEADERS, json={"prompt": "Explain a complete answer"}
    )
    assert response.status_code == HTTPStatus.OK
    assert "event: error" not in response.text
    assert '"provider_usage": {"prompt_tokens": 2, "completion_tokens": 3}' in response.text
    assert "data: [DONE]" in response.text
