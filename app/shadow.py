"""Opt-in, nonblocking fresh-answer sampling of cache hits for human review.

A different fresh answer is not automatically an incorrect cached answer. The
records deliberately contain no correctness label until independent review.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from typing import Any

from .cache.namespace import namespace
from .config import Settings, get_settings
from .logging_config import get_logger
from .metrics import SHADOW

log = get_logger("verigate.shadow")


def _check_length(length: int, maximum: int) -> None:
    if length > maximum:
        raise ValueError("Shadow answer exceeds configured response limit")


def _check_record_size(payload: str, maximum: int) -> None:
    if len(payload.encode("utf-8")) > maximum:
        raise ValueError("Shadow review record exceeds configured cache entry limit")


class ShadowAuditor:
    def __init__(self, redis_client: Any, providers: Any, config: Settings | None = None) -> None:
        self.redis = redis_client
        self.providers = providers
        self.config = config or get_settings()
        self.key_prefix = namespace()
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    def maybe_schedule(self, prompt: str, cached_answer: str, tenant: str) -> bool:
        """Schedule without awaiting upstream work or holding up a cache response."""
        settings = self.config
        if (
            self._closed
            or not settings.shadow_enabled
            or settings.shadow_sample_rate == 0
            or len(self._tasks) >= settings.shadow_max_pending
        ):
            return False
        if secrets.randbelow(1_000_000) >= int(settings.shadow_sample_rate * 1_000_000):
            return False
        task = asyncio.create_task(self._sample(prompt, cached_answer, tenant))
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        SHADOW.labels(outcome="scheduled").inc()
        return True

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()  # retrieve errors even if the request has ended

    async def _sample(self, prompt: str, cached_answer: str, tenant: str) -> None:
        stream = None
        try:
            budget_key = f"{self.key_prefix}:shadow:budget:{tenant}"
            await self.redis.set(budget_key, 0, nx=True, ex=86400)
            count = await self.redis.incr(budget_key)
            if count > self.config.shadow_daily_limit_per_tenant:
                SHADOW.labels(outcome="budget_exhausted").inc()
                return
            async with asyncio.timeout(self.config.provider_timeout):
                provider, stream = await self.providers.route_stream(prompt)
                chunks: list[str] = []
                size = 0
                async for chunk in stream:
                    size += len(chunk)
                    _check_length(size, self.config.max_response_chars)
                    chunks.append(chunk)
            fresh_answer = "".join(chunks).strip()
            record = {
                "id": uuid.uuid4().hex,
                "tenant_id": tenant,
                "prompt": prompt,
                "cached_answer": cached_answer,
                "fresh_answer": fresh_answer,
                "provider": provider,
                "observed_at": time.time(),
                "review_status": "unreviewed",
                "label": None,
            }
            payload = json.dumps(record)
            _check_record_size(payload, self.config.max_cache_entry_bytes)
            key = f"{self.key_prefix}:shadow:review:{tenant}"
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(key, payload)
                pipe.ltrim(key, 0, self.config.shadow_review_limit - 1)
                pipe.expire(key, self.config.cache_ttl_sec)
                await pipe.execute()
            SHADOW.labels(outcome="recorded").inc()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            SHADOW.labels(outcome="failed").inc()
            log.warning("shadow_sample_failed", error_type=type(exc).__name__, tenant=tenant)
        finally:
            if stream is not None and hasattr(stream, "aclose"):
                await stream.aclose()

    async def aclose(self) -> None:
        self._closed = True
        pending = tuple(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
