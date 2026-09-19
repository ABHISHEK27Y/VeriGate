"""Common provider interface. Adding a new LLM = implementing this class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class Provider(ABC):
    name: str = "base"
    price_per_1k_input: float = 0.0
    price_per_1k_output: float = 0.0

    @abstractmethod
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Yield answer tokens/chunks as they are produced."""
        raise NotImplementedError
        yield  # pragma: no cover

    async def health(self) -> str:
        """Return 'healthy' | 'degraded' | 'down'."""
        return "healthy"
