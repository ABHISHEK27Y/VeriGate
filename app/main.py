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
from .cache.namespace import POLICY_VERSION
from .cache.semantic_cache import LookupResult, SemanticCache
from .config import Settings, _runtime, get_settings, snapshot
from .embeddings import Embedder
from .identity import key_allowed, tenant_id
from .limits import RequestLimitsMiddleware
from .logging_config import LoggingMiddleware, configure_logging, get_logger
from .metrics import (
    BUDGET_EXCEEDED,
    CACHE,
    CACHE_FAILURES,
    CANDIDATE_DECISION,
    CANDIDATE_VERIFIER_REJECTED,
    LATENCY,
    RATE_LIMITED,
    REQUESTS,
    STAGE_LATENCY,
    render_metrics,
)
from .providers.registry import ProviderRegistry
from .rate_limit import RateLimiter
from .redis_client import close_redis, create_redis, redis_backend_name
from .schemas import ChatRequest, ChatResponse
from .shadow import ShadowAuditor
from .singleflight import SingleFlight

# Configure structured logging
configure_logging(json_output=True)
log = get_logger("verigate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: PLR0915
    """Application lifespan handler - startup and shutdown."""
    # Startup
    log.info("Starting VeriGate gateway", version=__version__)

    app.state.config = getattr(app.state, "config", snapshot())
    token = _runtime.set(app.state.config)
    redis_client = None
    binary_client = None
    pool_token = None
    try:
        redis_client = create_redis()
        app.state.redis = redis_client
        binary_client = create_redis(binary=True)
        app.state.binary_redis = binary_client
        pool_token = rs.active_client.set(binary_client)
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
        app.state.singleflight = SingleFlight()
        app.state.providers = app.state.provider_registry
        app.state.shadow_auditor = ShadowAuditor(
            app.state.redis, app.state.provider_registry, app.state.config
        )
        app.state.rate_limiter = RateLimiter(app.state.redis)
        app.state.budget_check = budget_check_and_count
        if (
            get_settings().embedding_backend == "minilm"
            and get_settings().cache_match_mode == "semantic"
        ):
            await asyncio.to_thread(app.state.model.embed, "warmup")
        if (
            get_settings().cache_match_mode == "semantic"
            and get_settings().answer_policy_artifact
            and get_settings().answer_policy_prewarm
        ):
            await asyncio.to_thread(app.state.semantic_cache._policy.verifier.prewarm)
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
        if hasattr(app.state, "shadow_auditor"):
            await app.state.shadow_auditor.aclose()
        if hasattr(app.state, "provider_registry"):
            await app.state.provider_registry.aclose()
        if redis_client is not None:
            await close_redis(redis_client)
        if binary_client is not None:
            await close_redis(binary_client)
        if pool_token is not None:
            rs.active_client.reset(pool_token)
        _runtime.reset(token)


app = FastAPI(
    title="VeriGate",
    version=__version__,
    lifespan=lifespan,
)
app.state.config = snapshot()

# CORS middleware
if app.state.config.cors_origins:
    origins = [o.strip() for o in app.state.config.cors_origins.split(",") if o.strip()]
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
    if not key_allowed(api_key, get_settings().api_key_set):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    assert api_key is not None
    return api_key


def _tenant(api_key: str) -> str:
    """Stable, opaque tenant id derived from the API key. The cache is partitioned by this,
    so no tenant can ever be served another tenant's cached answer (SECURITY.md #1)."""
    return tenant_id(api_key)


def _cache_tenant(request: Request, prompt: str, tenant: str) -> str:
    registry = request.app.state.provider_registry
    if registry.cascade:
        return f"{tenant}:{registry.intended_route(prompt)}"
    return tenant


async def _check_rate_limit(api_key: str, request: Request) -> None:
    try:
        allowed, remaining = await request.app.state.rate_limiter.allow(api_key)
    except Exception as exc:
        log.warning("rate_limit_unavailable", tenant=_tenant(api_key))
        raise HTTPException(status_code=503, detail="admission unavailable") from exc
    if not allowed:
        RATE_LIMITED.inc()
        REQUESTS.labels(outcome="rate_limited").inc()
        log.warning("Rate limit exceeded", tenant=_tenant(api_key))
        raise HTTPException(status_code=429, detail="rate limit exceeded")


async def _check_budget(api_key: str, request: Request) -> None:
    """Charge one admitted miss/bypass; cache hits never reach here."""
    try:
        admitted = await budget_check_and_count(api_key, request.app.state.redis)
    except Exception as exc:
        log.warning("budget_unavailable", tenant=_tenant(api_key))
        raise HTTPException(status_code=503, detail="admission unavailable") from exc
    if not admitted:
        BUDGET_EXCEEDED.inc()
        log.warning("Daily budget exceeded", tenant=_tenant(api_key))
        raise HTTPException(status_code=429, detail="daily request budget exceeded")


async def _cache_lookup(request: Request, prompt: str, tenant: str, bypass: bool) -> LookupResult:
    if bypass:
        return LookupResult(status="BYPASS", reason="requested_bypass")
    try:
        result: LookupResult = await request.app.state.semantic_cache.lookup(prompt, tenant)
    except Exception:
        CACHE_FAILURES.labels(stage="lookup").inc()
        log.warning("cache_lookup_failed", tenant=tenant)
        return LookupResult(status="MISS", reason="cache_unavailable")
    else:
        return result


async def _cache_store(request: Request, prompt: str, answer: str, tenant: str) -> None:
    started = time.perf_counter()
    try:
        await request.app.state.semantic_cache.store(prompt, answer, tenant)
    except Exception:
        CACHE_FAILURES.labels(stage="write").inc()
        log.warning("cache_write_failed", tenant=tenant)
    finally:
        STAGE_LATENCY.labels(stage="cache_write").observe(time.perf_counter() - started)


def _count_candidate_decision(result: LookupResult) -> None:
    reason = result.reason or ""
    if reason.startswith("answer_"):
        action = reason.split(":", 1)[0].removeprefix("answer_")
        if action in {"accept", "verify", "reject"}:
            CANDIDATE_DECISION.labels(action=action).inc()
    if reason.startswith("verify_rejected"):
        CANDIDATE_VERIFIER_REJECTED.inc()


def _check_response_length(length: int) -> None:
    if length > get_settings().max_response_chars:
        raise ResponseTooLargeError


class ResponseTooLargeError(Exception):
    """The configured upstream response limit was exceeded."""


async def _generate_answer(prompt: str, request: Request) -> tuple[str, str]:
    """Call the provider (with failover) and assemble the full answer."""
    stream = None
    generation_started = time.perf_counter()
    try:
        async with asyncio.timeout(get_settings().provider_timeout):
            route_started = time.perf_counter()
            provider_name, stream = await request.app.state.provider_registry.route_stream(prompt)
            STAGE_LATENCY.labels(stage="provider_first_token").observe(
                time.perf_counter() - route_started
            )
            chunks = []
            length = 0
            async for chunk in stream:
                length += len(chunk)
                _check_response_length(length)
                chunks.append(chunk)
    except TimeoutError as exc:
        log.warning("upstream_timeout")
        raise HTTPException(status_code=504, detail="upstream timeout") from exc
    except ResponseTooLargeError as exc:
        log.warning("upstream_response_too_large")
        raise HTTPException(status_code=502, detail="upstream response too large") from exc
    except Exception as exc:
        log.warning("upstream_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="upstream unavailable") from exc
    finally:
        STAGE_LATENCY.labels(stage="full_generation").observe(
            time.perf_counter() - generation_started
        )
        if stream is not None and hasattr(stream, "aclose"):
            await stream.aclose()
    answer = "".join(chunks).strip()
    if not answer:
        raise HTTPException(status_code=502, detail="empty upstream answer")
    return provider_name, answer


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
    tenant = _tenant(api_key)
    await request.app.state.semantic_cache.clear(tenant)
    for route in request.app.state.provider_registry.cache_scopes():
        await request.app.state.semantic_cache.clear(f"{tenant}:{route}")
    return {"status": "cleared"}


@app.get("/live")
async def live():
    return {"status": "alive"}


@app.get("/ready")
@app.get("/health")
async def health(request: Request):
    details = await _health_details(request)
    if get_settings().environment == "production":
        return {"status": details["status"]}
    return details


@app.get("/admin/config")
async def config_details(request: Request, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    return await _health_details(request)


async def _health_details(request: Request) -> dict:
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
        "cache_policy_version": POLICY_VERSION,
        "answer_policy_version": (
            request.app.state.semantic_cache._answer_policy.version[:12]
            if request.app.state.semantic_cache._answer_policy
            else None
        ),
        "answer_policy_prewarm": get_settings().answer_policy_prewarm,
        "verifier_nli_enabled": get_settings().verifier_nli,
        "provider_health": "configuration_only",
        "providers": (
            list(request.app.state.provider_registry.cache_scopes())
            if request.app.state.provider_registry.cascade
            else [p.name for p in request.app.state.provider_registry.providers]
        ),
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
    cache_tenant = _cache_tenant(request, prompt, tenant)
    intended_provider = request.app.state.provider_registry.intended_route(prompt)
    result = await _cache_lookup(request, prompt, cache_tenant, req.cache_bypass)
    _count_candidate_decision(result)

    if result.status == "HIT":
        request.app.state.shadow_auditor.maybe_schedule(
            prompt, result.answer or "", tenant, result.cached_query
        )
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
            intended_provider=intended_provider,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            threshold=result.threshold,
            similarity=result.similarity,
            note=result.reason,
        )

    await _check_budget(api_key, request)  # only miss/bypass reach a provider — hits are free
    path = "bypass" if result.status == "BYPASS" else "miss"

    async def generate_and_store() -> tuple[str, str]:
        provider_name, answer = await _generate_answer(prompt, request)
        if provider_name == intended_provider:
            await _cache_store(request, prompt, answer, cache_tenant)
        return provider_name, answer

    if result.status == "BYPASS":
        provider_name, answer = await _generate_answer(prompt, request)
        joined = False
    else:
        try:
            (provider_name, answer), joined = await request.app.state.singleflight.run(
                f"{cache_tenant}\x00{prompt}",
                generate_and_store,
                get_settings().provider_timeout + 2,
            )
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="coalesced request timeout") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail="upstream unavailable") from exc

    CACHE.labels(result=path).inc()
    REQUESTS.labels(outcome=path).inc()
    LATENCY.labels(path=path).observe(time.perf_counter() - t0)
    log.info("cache_miss", tenant=tenant, provider=provider_name, path=path)
    return ChatResponse(
        answer=answer,
        cache=result.status,
        provider=provider_name,
        intended_provider=intended_provider,
        fallback_used=provider_name != intended_provider,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        threshold=result.threshold,
        similarity=result.similarity,
        note=f"coalesced:{result.reason}" if joined else result.reason,
    )


@app.post("/v1/chat/stream")
async def chat_stream(  # noqa: PLR0915
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

    cache_tenant = _cache_tenant(request, prompt, tenant)
    intended_provider = request.app.state.provider_registry.intended_route(prompt)
    result = await _cache_lookup(request, prompt, cache_tenant, req.cache_bypass)
    _count_candidate_decision(result)
    if result.status != "HIT":
        await _check_budget(api_key, request)  # charge before streaming starts
        try:
            async with asyncio.timeout_at(deadline):
                route_started = time.perf_counter()
                provider_name, source = await request.app.state.provider_registry.route_stream(
                    prompt
                )
                STAGE_LATENCY.labels(stage="provider_first_token").observe(
                    time.perf_counter() - route_started
                )
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="upstream timeout") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="upstream unavailable") from exc

    async def event_gen():
        if result.status == "HIT":
            request.app.state.shadow_auditor.maybe_schedule(
                prompt, result.answer or "", tenant, result.cached_query
            )
            CACHE.labels(result="hit").inc()
            REQUESTS.labels(outcome="hit").inc()
            LATENCY.labels(path="hit").observe(time.perf_counter() - started)
            yield f"data: {json.dumps(result.answer)}\n\n"
            yield "data: [DONE]\n\n"
            return
        buf = []
        length = 0
        generation_started = time.perf_counter()
        try:
            async with asyncio.timeout_at(deadline):
                async for chunk in source:
                    length += len(chunk)
                    _check_response_length(length)
                    buf.append(chunk)
                    yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:
            log.warning("upstream_stream_failed")
            REQUESTS.labels(outcome="stream_error").inc()
            LATENCY.labels(path="stream_error").observe(time.perf_counter() - started)
            code = (
                "upstream response too large"
                if isinstance(exc, ResponseTooLargeError)
                else "upstream timeout"
                if isinstance(exc, TimeoutError)
                else "upstream unavailable"
            )
            yield f"event: error\ndata: {json.dumps({'error': code})}\n\n"
            return
        finally:
            STAGE_LATENCY.labels(stage="full_generation").observe(
                time.perf_counter() - generation_started
            )
            if hasattr(source, "aclose"):
                await source.aclose()
        answer = "".join(buf).strip()
        if not answer:
            REQUESTS.labels(outcome="stream_error").inc()
            LATENCY.labels(path="stream_error").observe(time.perf_counter() - started)
            yield 'event: error\ndata: {"error":"empty upstream answer"}\n\n'
            return
        if result.status != "BYPASS" and provider_name == intended_provider:
            await _cache_store(request, prompt, answer, cache_tenant)
        path = "bypass" if result.status == "BYPASS" else "miss"
        CACHE.labels(result=path).inc()
        REQUESTS.labels(outcome=path).inc()
        LATENCY.labels(path=path).observe(time.perf_counter() - started)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "X-Provider": "cache" if result.status == "HIT" else provider_name,
            "X-Intended-Provider": intended_provider,
        },
    )


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
