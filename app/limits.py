"""Bound request buffering and admission for the entire response lifetime."""

from __future__ import annotations

import asyncio
import time

from starlette.responses import JSONResponse

from .cache import redisearch_store as rs
from .config import _runtime, snapshot
from .identity import key_allowed
from .metrics import CLIENT_COMPLETE, CLIENT_TTFB


class RequestLimitsMiddleware:
    def __init__(self, app, owner):
        self.app = app
        self.owner = owner
        self.active = 0

    async def __call__(self, scope, receive, send):  # noqa: PLR0911, PLR0915
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        first_body = False

        async def timed_send(message):
            nonlocal first_body
            if message["type"] == "http.response.body":
                if message.get("body") and not first_body:
                    first_body = True
                    CLIENT_TTFB.observe(time.perf_counter() - started)
                if not message.get("more_body", False):
                    CLIENT_COMPLETE.observe(time.perf_counter() - started)
            await send(message)

        config = getattr(self.owner.state, "config", None) or snapshot()
        token = _runtime.set(config)
        pool_token = rs.active_client.set(getattr(self.owner.state, "binary_redis", None))
        admitted = False
        try:
            if scope.get("method") == "POST" and scope.get("path") in {
                "/v1/chat",
                "/v1/chat/stream",
                "/admin/cache/clear",
            }:
                headers = dict(scope.get("headers", []))
                supplied = headers.get(b"x-api-key", b"").decode("latin-1")
                directory = getattr(self.owner.state, "organization_directory", None)
                try:
                    authorized = (
                        directory.resolve(supplied) is not None
                        if directory is not None
                        else key_allowed(supplied, config.api_key_set)
                    )
                except (OSError, ValueError, TypeError):
                    return await JSONResponse({"detail": "identity directory unavailable"}, 503)(
                        scope, receive, timed_send
                    )
                if not authorized:
                    return await JSONResponse({"detail": "invalid or missing API key"}, 401)(
                        scope, receive, timed_send
                    )
            if self.active >= config.max_concurrent_requests:
                return await JSONResponse({"detail": "server busy"}, 503)(
                    scope, receive, timed_send
                )
            self.active += 1
            admitted = True
            body = bytearray()
            try:
                async with asyncio.timeout(config.request_body_timeout):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > config.max_request_bytes:
                            return await JSONResponse({"detail": "request too large"}, 413)(
                                scope, receive, timed_send
                            )
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await JSONResponse({"detail": "request body timed out"}, 408)(
                    scope, receive, timed_send
                )

            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, buffered_receive, timed_send)
        finally:
            if admitted:
                self.active -= 1
            rs.active_client.reset(pool_token)
            _runtime.reset(token)
