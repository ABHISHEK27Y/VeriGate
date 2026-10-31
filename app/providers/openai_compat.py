"""An OpenAI-compatible streaming provider.

One class covers multiple vendors because they expose the same `/chat/completions` API:
  * OpenAI  -> base_url https://api.openai.com/v1
  * Gemini  -> base_url https://generativelanguage.googleapis.com/v1beta/openai
              (Google's OpenAI-compatibility endpoint)
  * Others  -> any OpenAI-compatible base_url (Groq, Together, local vLLM, ...)

Keys are read from settings (.env) — never hardcoded, never logged. Streaming is parsed
from the Server-Sent-Events `data:` lines.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..config import get_settings
from .base import Provider, ProviderEvent


class OpenAICompatibleProvider(Provider):
    def __init__(
        self, name: str, api_key: str, base_url: str, model: str, timeout: float | None = None
    ) -> None:
        self.name = name
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._model = model
        # Use settings timeout if not explicitly provided
        self._timeout = timeout if timeout is not None else get_settings().provider_timeout
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=min(5.0, self._timeout)),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.stream_events(prompt):
            if event.kind == "content":
                yield event.content

    async def stream_events(self, prompt: str) -> AsyncIterator[ProviderEvent]:  # noqa: PLR0912, PLR0915
        url = f"{self._base}/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}"}
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if self.name.startswith("openai"):
            payload["stream_options"] = {"include_usage": True}
            payload["max_completion_tokens"] = get_settings().provider_max_completion_tokens
        else:
            payload["max_tokens"] = get_settings().provider_max_completion_tokens
        async with self._client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            finished = False
            finish_reason = None
            usage = None
            response_model = None
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    finished = True
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Malformed upstream stream event") from exc
                if not isinstance(obj, dict):
                    raise TypeError("Malformed upstream stream event")
                if isinstance(obj.get("model"), str):
                    response_model = obj["model"]
                if isinstance(obj.get("usage"), dict):
                    usage = {
                        key: value
                        for key, value in obj["usage"].items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                        and isinstance(value, int)
                        and value >= 0
                    }
                choices = obj.get("choices")
                if choices == [] and usage is not None:
                    continue
                if not isinstance(choices, list) or len(choices) != 1:
                    raise RuntimeError("Unsupported upstream answer event")
                choice = choices[0]
                if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
                    raise TypeError("Malformed upstream answer event")
                delta = choice["delta"]
                if delta.get("tool_calls") or delta.get("function_call") or delta.get("refusal"):
                    raise RuntimeError("Unsupported upstream non-answer output")
                content = delta.get("content")
                if content is not None and not isinstance(content, str):
                    raise RuntimeError("Malformed upstream answer content")
                if content:
                    yield ProviderEvent("content", content=content, model=obj.get("model"))
                reason = choice.get("finish_reason")
                if reason is not None:
                    if not isinstance(reason, str):
                        raise RuntimeError("Malformed upstream finish reason")
                    finish_reason = reason
            if not finished:
                raise RuntimeError("Upstream stream ended without completion marker")
            yield ProviderEvent(
                "complete",
                finish_reason=finish_reason,
                model=response_model or self._model,
                usage=usage,
            )

    async def health(self) -> str:
        # Optimistic: real failures surface at call time and trigger failover.
        return "configured; upstream not probed"
