"""Structured logging configuration for VeriGate.

Uses structlog for JSON output with contextvars (request_id, tenant, etc.).
"""

from __future__ import annotations

import hashlib
import logging
import sys
import uuid

import structlog


def configure_logging(
    level: int = logging.INFO,
    json_output: bool = True,
) -> None:
    """Configure structlog for the application.

    Args:
        level: Logging level (default INFO)
        json_output: If True, output JSON lines; else pretty console output
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer: structlog.typing.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # Reduce noise from verbose libraries
    for noisy_logger in ["httpx", "httpcore", "urllib3", "redis", "fakeredis"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structlog logger with the given name."""
    return structlog.get_logger(name)


class LoggingMiddleware:
    """ASGI middleware to add request context to logs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]

        # Bind request_id to contextvars for this request
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Extract tenant from header if present
        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode() if b"x-api-key" in headers else None
        if api_key:
            # Use same tenant derivation as main.py
            tenant = "t_" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
            structlog.contextvars.bind_contextvars(tenant=tenant)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status = message.get("status", 0)
                structlog.contextvars.bind_contextvars(status_code=status)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.clear_contextvars()
