"""Generation-checked shared breaker with an owned half-open lease."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus

import httpx
from redis.exceptions import WatchError

from ..cache.namespace import namespace
from ..config import get_settings


@dataclass(frozen=True)
class Ticket:
    generation: str | None
    probe: str | None = None


def _keys(name: str) -> tuple[str, str, str, str]:
    return (
        f"{namespace()}:breaker:open:{name}",
        f"{namespace()}:breaker:fails:{name}",
        f"{namespace()}:breaker:probe:{name}",
        f"{namespace()}:breaker:generation:{name}",
    )


async def acquire(name: str, r) -> Ticket | None:
    opened, _, probe, generation = _keys(name)
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(opened, probe, generation)
                until = await pipe.get(opened)
                version = await pipe.get(generation)
                if until is None:
                    return Ticket(version)
                if float(until) > time.time() or await pipe.get(probe):
                    return None
                owner = uuid.uuid4().hex
                pipe.multi()
                # Covers prefetch and streaming deadlines, with a scheduling margin.
                pipe.set(probe, owner, ex=math.ceil(get_settings().provider_timeout * 2) + 5)
                await pipe.execute()
                return Ticket(version, owner)
        except WatchError:
            continue
    return None


async def is_open(name: str, r) -> bool:
    return await acquire(name, r) is None


def transient(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return (
            error.response.status_code == HTTPStatus.TOO_MANY_REQUESTS
            or error.response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
        )
    return isinstance(error, httpx.TransportError | TimeoutError | RuntimeError | OSError)


async def record_failure(name: str, r, ticket: Ticket | None = None) -> None:
    opened, fails, probe, generation = _keys(name)
    config = get_settings()
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(opened, fails, probe, generation)
                if ticket and ticket.probe and await pipe.get(probe) != ticket.probe:
                    return  # expired/replaced probes do not own the breaker anymore
                count = int(await pipe.get(fails) or 0) + 1
                pipe.multi()
                lifetime = config.breaker_cooldown_sec + math.ceil(config.provider_timeout * 2) + 60
                pipe.set(generation, uuid.uuid4().hex, ex=lifetime)
                pipe.set(fails, count, ex=config.breaker_window_sec)
                if count >= config.breaker_fail_threshold or (ticket and ticket.probe):
                    pipe.set(opened, str(time.time() + config.breaker_cooldown_sec), ex=lifetime)
                if ticket and ticket.probe:
                    pipe.delete(probe)
                await pipe.execute()
                return
        except WatchError:
            continue
    raise RuntimeError("Breaker update contention")


async def record_success(name: str, r, ticket: Ticket | None = None) -> None:
    opened, fails, probe, generation = _keys(name)
    # No ticket is reserved for explicit administrative reset / standalone tests.
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(opened, fails, probe, generation)
                if ticket is not None:
                    if await pipe.get(generation) != ticket.generation:
                        return
                    if ticket.probe and await pipe.get(probe) != ticket.probe:
                        return
                    if not ticket.probe and await pipe.get(opened):
                        return
                pipe.multi()
                pipe.delete(opened, fails, probe, generation)
                await pipe.execute()
                return
        except WatchError:
            continue
    raise RuntimeError("Breaker update contention")
