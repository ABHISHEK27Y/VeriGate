"""Bound request buffering and admission for the entire response lifetime."""

from __future__ import annotations

import asyncio

from starlette.responses import JSONResponse

from .cache import redisearch_store as rs
from .config import _runtime, snapshot


class RequestLimitsMiddleware:
    def __init__(self, app, owner):
        self.app = app
        self.owner = owner
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        config = getattr(self.owner.state, "config", None) or snapshot()
        token = _runtime.set(config)
        pool_token = rs.active_client.set(getattr(self.owner.state, "binary_redis", None))
        admitted = False
        try:
            if self.active >= config.max_concurrent_requests:
                return await JSONResponse({"detail": "server busy"}, 503)(scope, receive, send)
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
                                scope, receive, send
                            )
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await JSONResponse({"detail": "request body timed out"}, 408)(
                    scope, receive, send
                )

            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, buffered_receive, send)
        finally:
            if admitted:
                self.active -= 1
            rs.active_client.reset(pool_token)
            _runtime.reset(token)
