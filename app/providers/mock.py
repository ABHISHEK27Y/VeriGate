"""A free, deterministic mock provider.

Lets you run and load-test the ENTIRE gateway with no API keys and no cost. Answers are
deterministic per prompt so cache behaviour is easy to observe and test.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .base import Provider


class MockProvider(Provider):
    name = "mock"
    price_per_1k_input = 0.0
    price_per_1k_output = 0.0

    def __init__(self, delay: float = 0.02, name_override: str | None = None) -> None:
        self.delay = delay  # simulate per-token latency
        if name_override:
            self.name = name_override

    def _answer(self, prompt: str) -> str:
        return f"[mock:{self.name}] Answer to: {prompt}"

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        for word in self._answer(prompt).split(" "):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield word + " "


class FlakyProvider(MockProvider):
    """A mock that fails on demand, to demonstrate failover / circuit breaking."""

    name = "flaky"

    def __init__(self, fail: bool = True, delay: float = 0.02) -> None:
        super().__init__(delay=delay)
        self.fail = fail

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        if self.fail:
            raise RuntimeError("simulated provider outage")
        async for chunk in super().stream(prompt):
            yield chunk

    async def health(self) -> str:
        return "down" if self.fail else "healthy"
