"""Common provider interface. Adding a new LLM = implementing this class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    kind: Literal["content", "complete"]
    content: str = ""
    finish_reason: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None


class Provider(ABC):
    name: str = "base"
    implicit_completion_is_safe: bool = False
    price_per_1k_input: float = 0.0
    price_per_1k_output: float = 0.0

    @abstractmethod
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Yield answer tokens/chunks as they are produced."""
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream_events(self, prompt: str) -> AsyncIterator[ProviderEvent]:
        """Adapt controlled/mock providers; real adapters override with upstream metadata."""
        if not self.implicit_completion_is_safe:
            raise RuntimeError("Provider must report explicit completion metadata")
        async for content in self.stream(prompt):
            yield ProviderEvent("content", content=content)
        yield ProviderEvent("complete", finish_reason="stop")

    async def health(self) -> str:
        """Return 'healthy' | 'degraded' | 'down'."""
        return "healthy"
