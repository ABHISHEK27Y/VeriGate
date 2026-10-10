"""VeriGate gateway — FastAPI app wiring the whole pipeline together.

Pipeline per request (see docs/ARCHITECTURE.md):
  auth -> rate limit -> [staleness -> semantic cache lookup] -> provider+stream -> store -> meter
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST

from . import __version__
from .budget import check_and_count as budget_check_and_count
from .cache import redisearch_store as rs
from .cache.semantic_cache import LookupResult, SemanticCache
from .config import Settings, _runtime, get_settings, snapshot
from .embeddings import Embedder
from .identity import tenant_id
from .limits import RequestLimitsMiddleware
from .logging_config import LoggingMiddleware, configure_logging, get_logger
from .metrics import (
    BUDGET_EXCEEDED,
    CACHE,
    FALSE_HIT_REJECTED,
    LATENCY,
    RATE_LIMITED,
    REQUESTS,
    render_metrics,
)
from .providers.registry import ProviderRegistry
from .rate_limit import RateLimiter
from .redis_client import close_redis, create_redis, redis_backend_name
from .schemas import ChatRequest, ChatResponse

# Configure structured logging
configure_logging(json_output=True)
log = get_logger("verigate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup and shutdown."""
    # Startup
    log.info("Starting VeriGate gateway", version=__version__)

    app.state.config = getattr(app.state, "config", snapshot())
    token = _runtime.set(app.state.config)
    app.state.redis = create_redis()
    app.state.binary_redis = create_redis(binary=True)
    pool_token = rs.active_client.set(app.state.binary_redis)
    try:
        get_settings().validate_production()
        await app.state.redis.ping()
        if get_settings().environment == "production":
            memory = await app.state.redis.info("memory")
            if int(memory.get("maxmemory", 0)) <= 0:
                raise ValueError("Production Redis requires a finite maxmemory setting")
        app.state.model = Embedder()
        app.state.semantic_cache = SemanticCache(app.state.redis, app.state.model)
        app.state.cache = app.state.semantic_cache
        app.state.index = app.state.cache._index
        app.state.verifier = app.state.cache._policy.verifier
        app.state.provider_registry = ProviderRegistry.from_settings(app.state.redis)
        app.state.providers = app.state.provider_registry
        app.state.rate_limiter = RateLimiter(app.state.redis)
        app.state.budget_check = budget_check_and_count
        if (
            get_settings().embedding_backend == "minilm"
            and get_settings().cache_match_mode == "semantic"
        ):
            await asyncio.to_thread(app.state.model.embed, "warmup")
        if (
            get_settings().vector_backend == "redisearch"
            and get_settings().cache_match_mode == "semantic"
        ):
            vec = await asyncio.to_thread(app.state.model.embed, "dimension probe")
            app.state.embedding_dimension = len(vec)
            await rs.ensure_index(app.state.embedding_dimension)
        yield
    finally:
        log.info("Shutting down VeriGate gateway")
        if hasattr(app.state, "provider_registry"):
            await app.state.provider_registry.aclose()
        await close_redis(app.state.redis)
        await close_redis(app.state.binary_redis)
        rs.active_client.reset(pool_token)
        _runtime.reset(token)


app = FastAPI(
    title="VeriGate",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware
if get_settings().cors_origins:
    origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
else:
    origins = []  # same-origin unless explicitly configured

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware (adds request_id, tenant to contextvars)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestLimitsMiddleware, owner=app)


def _auth(api_key: str | None) -> str:
    if not api_key or api_key not in get_settings().api_key_set:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return api_key


def _tenant(api_key: str) -> str:
    """Stable, opaque tenant id derived from the API key. The cache is partitioned by this,
    so no tenant can ever be served another tenant's cached answer (SECURITY.md #1)."""
    return tenant_id(api_key)


async def _check_rate_limit(api_key: str, request: Request) -> None:
    allowed, remaining = await request.app.state.rate_limiter.allow(api_key)
    if not allowed:
        RATE_LIMITED.inc()
        REQUESTS.labels(outcome="rate_limited").inc()
        log.warning("Rate limit exceeded", tenant=_tenant(api_key))
        raise HTTPException(status_code=429, detail="rate limit exceeded")


async def _check_budget(api_key: str, request: Request) -> None:
    """Charge one admitted miss/bypass; cache hits never reach here."""
    if not await budget_check_and_count(api_key, request.app.state.redis):
        BUDGET_EXCEEDED.inc()
        log.warning("Daily budget exceeded", tenant=_tenant(api_key))
        raise HTTPException(status_code=429, detail="daily request budget exceeded")


def _check_response_length(length: int) -> None:
    if length > get_settings().max_response_chars:
        raise RuntimeError("Provider response exceeds configured limit")


async def _generate_answer(prompt: str, request: Request) -> tuple[str, str]:
    """Call the provider (with failover) and assemble the full answer."""
    stream = None
    try:
        async with asyncio.timeout(get_settings().provider_timeout):
            provider_name, stream = await request.app.state.provider_registry.route_stream(prompt)
            chunks = []
            length = 0
            async for chunk in stream:
                length += len(chunk)
                _check_response_length(length)
                chunks.append(chunk)
        return provider_name, "".join(chunks).strip()
    except Exception as exc:
        log.warning("upstream_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="upstream unavailable") from exc
    finally:
        if stream is not None and hasattr(stream, "aclose"):
            await stream.aclose()


_UI_FILE = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/")
@app.get("/ui")
def dashboard():
    """Interactive web dashboard for testing the gateway (served same-origin)."""
    return FileResponse(_UI_FILE)


@app.post("/admin/cache/clear")
async def clear_cache(request: Request, x_api_key: str | None = Header(default=None)):
    """Clear the caller's own tenant cache (requires a valid API key). Used by the dashboard."""
    api_key = _auth(x_api_key)
    await request.app.state.semantic_cache.clear(_tenant(api_key))
    return {"status": "cleared"}


@app.get("/live")
async def live():
    return {"status": "alive"}


@app.get("/ready")
@app.get("/health")
async def health(request: Request):
    try:
        await request.app.state.redis.ping()
        if (
            get_settings().vector_backend == "redisearch"
            and get_settings().cache_match_mode == "semantic"
        ):
            await rs.validate_index(request.app.state.embedding_dimension)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
    return {
        "status": "ok",
        "version": __version__,
        "redis": redis_backend_name(),
        "embedding_backend": request.app.state.model.backend,
        "vector_backend": get_settings().vector_backend,
        "cache_enabled": get_settings().cache_enabled,
        "cache_match_mode": get_settings().cache_match_mode,
        "provider_health": "configuration_only",
        "providers": [p.name for p in request.app.state.provider_registry.providers],
    }


async def verify_metrics_token(
    x_metrics_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    if authorization and authorization.startswith("Bearer "):
        x_metrics_token = authorization[7:]
    if (
        not x_metrics_token
        or not get_settings().metrics_token
        or not hmac.compare_digest(x_metrics_token, get_settings().metrics_token)
    ):
        raise HTTPException(status_code=401, detail="invalid metrics token")


@app.get("/metrics", dependencies=[Depends(verify_metrics_token)])
def metrics():
    return PlainTextResponse(render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)):
    """Non-streaming JSON endpoint — easiest to test/inspect (see X-Cache in the body)."""
    api_key = _auth(x_api_key)
    await _check_rate_limit(api_key, request)
    tenant = _tenant(api_key)

    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    t0 = time.perf_counter()
    result: LookupResult = await request.app.state.semantic_cache.lookup(prompt, tenant)

    if result.status == "HIT":
        CACHE.labels(result="hit").inc()
        REQUESTS.labels(outcome="hit").inc()
        LATENCY.labels(path="hit").observe(time.perf_counter() - t0)
        log.info(
            "cache_hit", tenant=tenant, similarity=result.similarity, threshold=result.threshold
        )
        return ChatResponse(
            answer=result.answer or "",
            cache="HIT",
            provider="cache",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            threshold=result.threshold,
            similarity=result.similarity,
            note=result.reason,
        )

    # Track verifier rejections separately (the novelty's key metric)
    if result.reason and result.reason.startswith("verify_rejected"):
        FALSE_HIT_REJECTED.inc()

    await _check_budget(api_key, request)  # only miss/bypass reach a provider — hits are free
    provider_name, answer = await _generate_answer(prompt, request)

    path = "bypass" if result.status == "BYPASS" else "miss"
    if result.status != "BYPASS":
        await request.app.state.semantic_cache.store(prompt, answer, tenant)

    CACHE.labels(result=path).inc()
    REQUESTS.labels(outcome=path).inc()
    LATENCY.labels(path=path).observe(time.perf_counter() - t0)
    log.info("cache_miss", tenant=tenant, provider=provider_name, path=path)
    return ChatResponse(
        answer=answer,
        cache=result.status,
        provider=provider_name,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        threshold=result.threshold,
        similarity=result.similarity,
        note=result.reason,
    )


@app.post("/v1/chat/stream")
async def chat_stream(
    req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None)
):
    """Streaming endpoint (Server-Sent Events). Cache hits stream instantly."""
    started = time.perf_counter()
    deadline = asyncio.get_running_loop().time() + get_settings().provider_timeout
    api_key = _auth(x_api_key)
    await _check_rate_limit(api_key, request)
    tenant = _tenant(api_key)
    prompt = req.as_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="empty prompt")

    result: LookupResult = await request.app.state.semantic_cache.lookup(prompt, tenant)
    if result.status != "HIT":
        await _check_budget(api_key, request)  # charge before streaming starts
        try:
            async with asyncio.timeout_at(deadline):
                _, source = await request.app.state.provider_registry.route_stream(prompt)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="upstream unavailable") from exc

    async def event_gen():
        if result.status == "HIT":
            CACHE.labels(result="hit").inc()
            REQUESTS.labels(outcome="hit").inc()
            LATENCY.labels(path="hit").observe(time.perf_counter() - started)
            yield f"data: {json.dumps(result.answer)}\n\n"
            yield "data: [DONE]\n\n"
            return
        if result.reason and result.reason.startswith("verify_rejected"):
            FALSE_HIT_REJECTED.inc()
        buf = []
        length = 0
        try:
            async with asyncio.timeout_at(deadline):
                async for chunk in source:
                    length += len(chunk)
                    _check_response_length(length)
                    buf.append(chunk)
                    yield f"data: {json.dumps(chunk)}\n\n"
        except Exception:
            log.warning("upstream_stream_failed")
            REQUESTS.labels(outcome="stream_error").inc()
            LATENCY.labels(path="stream_error").observe(time.perf_counter() - started)
            yield 'event: error\ndata: {"error":"upstream unavailable"}\n\n'
            return
        finally:
            if hasattr(source, "aclose"):
                await source.aclose()
        if result.status != "BYPASS":
            await request.app.state.semantic_cache.store(prompt, "".join(buf).strip(), tenant)
        path = "bypass" if result.status == "BYPASS" else "miss"
        CACHE.labels(result=path).inc()
        REQUESTS.labels(outcome=path).inc()
        LATENCY.labels(path=path).observe(time.perf_counter() - started)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def create_app(config: Settings | None = None) -> FastAPI:
    """Create an isolated gateway; configuration changes require a new application."""
    gateway = FastAPI(title="VeriGate", version=__version__, lifespan=lifespan)
    gateway.state.config = snapshot(config)
    gateway.router.routes.extend(app.router.routes)
    origins = [v.strip() for v in gateway.state.config.cors_origins.split(",") if v.strip()]
    gateway.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    gateway.add_middleware(LoggingMiddleware)
    gateway.add_middleware(RequestLimitsMiddleware, owner=gateway)
    return gateway
