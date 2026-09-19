"""Provider registry + router with failover and (optional) cost-aware cascade.

Failover: try providers in order; on error, fall through to the next (mock is always last).
Cascade: when enabled, a query-complexity classifier picks the cheap model for easy queries
and the strong model for hard ones, cutting cost while preserving quality (see
evaluation/cascade.py). The unused tier stays as failover.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from ..complexity import is_hard
from ..config import settings
from . import breaker
from .base import Provider
from .mock import MockProvider
from .openai_compat import OpenAICompatibleProvider


def _real(name, key, base, model):
    return OpenAICompatibleProvider(name, key, base, model)


def build_from_settings() -> list[Provider]:
    """Single-model order: a real provider first (if a key is set), mock always last."""
    provs: list[Provider] = []
    if settings.llm_provider == "openai" and settings.openai_api_key:
        provs.append(_real("openai", settings.openai_api_key, settings.openai_base_url, settings.openai_model))
    elif settings.llm_provider == "gemini" and settings.gemini_api_key:
        provs.append(_real("gemini", settings.gemini_api_key, settings.gemini_base_url, settings.gemini_model))
    provs.append(MockProvider())
    return provs


def build_cascade() -> dict | None:
    """Build {cheap, strong} providers when cascade is enabled, else None."""
    if not settings.cascade_enabled:
        return None
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        k, b = settings.gemini_api_key, settings.gemini_base_url
        return {"cheap": _real("gemini-cheap", k, b, settings.gemini_model),
                "strong": _real("gemini-strong", k, b, settings.gemini_strong_model)}
    if settings.llm_provider == "openai" and settings.openai_api_key:
        k, b = settings.openai_api_key, settings.openai_base_url
        return {"cheap": _real("openai-cheap", k, b, settings.openai_model),
                "strong": _real("openai-strong", k, b, settings.openai_strong_model)}
    # no real key -> demonstrate with two mock tiers
    return {"cheap": MockProvider(name_override="mock-cheap"),
            "strong": MockProvider(name_override="mock-strong")}


_PROVIDERS: list[Provider] = build_from_settings()
_CASCADE: dict | None = build_cascade()


def providers() -> list[Provider]:
    return _PROVIDERS


def set_providers(p: list[Provider]) -> None:
    global _PROVIDERS
    _PROVIDERS = p


def set_cascade(cheap: Provider | None, strong: Provider | None) -> None:
    global _CASCADE
    _CASCADE = None if (cheap is None or strong is None) else {"cheap": cheap, "strong": strong}


def _order_for(prompt: str) -> list[Provider]:
    if _CASCADE:
        if is_hard(prompt, settings.cascade_threshold):
            return [_CASCADE["strong"], _CASCADE["cheap"]]   # escalate; cheap as failover
        return [_CASCADE["cheap"], _CASCADE["strong"]]       # cheap first; strong as failover
    return _PROVIDERS


async def route_stream(prompt: str) -> tuple[str, AsyncIterator[str]]:
    """Pick a provider (cascade + circuit-breaker + failover) -> (name, token_stream)."""
    last_err: Exception | None = None
    order = _order_for(prompt)
    # skip providers whose breaker is open, unless every provider is tripped (then try anyway)
    healthy = [p for p in order if not breaker.is_open(p.name)]
    for p in (healthy or order):
        try:
            agen = p.stream(prompt)
            first = await agen.__anext__()
            breaker.record_success(p.name)

            async def _wrapped(first_chunk=first, gen=agen):
                yield first_chunk
                async for chunk in gen:
                    yield chunk

            return p.name, _wrapped()
        except StopAsyncIteration:
            breaker.record_success(p.name)
            return p.name, _empty()
        except Exception as e:  # noqa: BLE001
            breaker.record_failure(p.name)
            last_err = e
            continue
    raise RuntimeError(f"all providers failed: {last_err}")


async def _empty() -> AsyncIterator[str]:
    if False:
        yield ""  # pragma: no cover
