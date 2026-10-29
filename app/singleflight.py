"""Bounded, process-local coalescing of identical JSON cache misses."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

T = TypeVar("T")


class SingleFlight:
    def __init__(self, capacity: int = 128) -> None:
        self.capacity = capacity
        self._active: dict[str, asyncio.Future[object]] = {}
        self._lock = asyncio.Lock()

    async def run(
        self, key: str, work: Callable[[], Awaitable[T]], wait_timeout: float
    ) -> tuple[T, bool]:
        """Return (result, joined). Capacity overflow runs independently."""
        async with self._lock:
            future = self._active.get(key)
            joined = future is not None
            if future is None and len(self._active) < self.capacity:
                future = asyncio.get_running_loop().create_future()
                self._active[key] = future
        if future is None:
            return await work(), False
        if joined:
            async with asyncio.timeout(wait_timeout):
                result = await asyncio.shield(future)
            return cast(T, result), True
        try:
            async with asyncio.timeout(wait_timeout):
                result = await work()
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                future.set_exception(RuntimeError("coalesced leader cancelled"))
            else:
                future.set_exception(exc)
            # The leader can fail before another request joins. Mark observed.
            future.exception()
            raise
        else:
            future.set_result(result)
            return result, False
        finally:
            async with self._lock:
                if self._active.get(key) is future:
                    del self._active[key]
