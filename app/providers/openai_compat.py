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

from .base import Provider


class OpenAICompatibleProvider(Provider):
    def __init__(self, name: str, api_key: str, base_url: str, model: str,
                 timeout: float = 60.0) -> None:
        self.name = name
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        url = f"{self._base}/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}"}
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta

    async def health(self) -> str:
        # Optimistic: real failures surface at call time and trigger failover.
        return "healthy"
