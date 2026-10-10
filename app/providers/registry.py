"""Provider registry + router with failover and (optional) cost-aware cascade.

Failover uses only explicitly configured providers; real failures never return mock answers.
Cascade: when enabled, a query-complexity classifier picks the cheap model for easy queries
and the strong model for hard ones, cutting cost while preserving quality (see
evaluation/cascade.py). The unused tier stays as failover.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ..complexity import is_hard
from ..config import get_settings
from ..redis_client import create_redis
from . import breaker
from .base import Provider
from .mock import MockProvider
from .openai_compat import OpenAICompatibleProvider


def _real(name: str, key: str, base: str, model: str) -> Provider:
    return OpenAICompatibleProvider(name, key, base, model)


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """Immutable provider registry with failover and cascade support."""

    providers: tuple[Provider, ...]
    cascade: Mapping[str, Provider] | None = None  # {"cheap": Provider, "strong": Provider}

    redis: Any = field(default_factory=create_redis, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "providers", tuple(self.providers))
        if self.cascade is not None:
            object.__setattr__(self, "cascade", MappingProxyType(dict(self.cascade)))

    @classmethod
    def from_settings(cls, redis_client=None) -> ProviderRegistry:
        """Build registry from configuration get_settings()."""
        provs: list[Provider] = []
        if get_settings().llm_provider == "openai" and get_settings().openai_api_key:
            provs.append(
                _real(
                    "openai",
                    get_settings().openai_api_key,
                    get_settings().openai_base_url,
                    get_settings().openai_model,
                )
            )
        elif get_settings().llm_provider == "gemini" and get_settings().gemini_api_key:
            provs.append(
                _real(
                    "gemini",
                    get_settings().gemini_api_key,
                    get_settings().gemini_base_url,
                    get_settings().gemini_model,
                )
            )
        if get_settings().llm_provider == "mock":
            provs.append(MockProvider())
        elif not provs:
            raise ValueError("Configured provider is unsupported or missing its API key")

        cascade = None
        if get_settings().cascade_enabled:
            if get_settings().llm_provider == "gemini" and get_settings().gemini_api_key:
                k, b = get_settings().gemini_api_key, get_settings().gemini_base_url
                cascade = {
                    "cheap": _real("gemini-cheap", k, b, get_settings().gemini_model),
                    "strong": _real("gemini-strong", k, b, get_settings().gemini_strong_model),
                }
            elif get_settings().llm_provider == "openai" and get_settings().openai_api_key:
                k, b = get_settings().openai_api_key, get_settings().openai_base_url
                cascade = {
                    "cheap": _real("openai-cheap", k, b, get_settings().openai_model),
                    "strong": _real("openai-strong", k, b, get_settings().openai_strong_model),
                }
            else:
                # no real key -> demonstrate with two mock tiers
                cascade = {
                    "cheap": MockProvider(name_override="mock-cheap"),
                    "strong": MockProvider(name_override="mock-strong"),
                }

        return cls(
            providers=tuple(provs),
            cascade=cascade,
            redis=redis_client if redis_client is not None else create_redis(),
        )

    async def aclose(self) -> None:
        providers = [*self.providers, *(self.cascade.values() if self.cascade else [])]
        seen = set()
        for provider in providers:
            if id(provider) not in seen and hasattr(provider, "aclose"):
                seen.add(id(provider))
                await provider.aclose()

    def _order_for(self, prompt: str) -> list[Provider]:
        if self.cascade:
            if is_hard(prompt, get_settings().cascade_threshold):
                return [
                    self.cascade["strong"],
                    self.cascade["cheap"],
                ]  # escalate; cheap as failover
            return [
                self.cascade["cheap"],
                self.cascade["strong"],
            ]  # cheap first; strong as failover
        return list(self.providers)

    async def route_stream(self, prompt: str) -> tuple[str, AsyncIterator[str]]:
        """Pick a provider (cascade + circuit-breaker + failover) -> (name, token_stream)."""
        last_err: Exception | None = None
        order = self._order_for(prompt)
        # Acquire ownership before attempting upstream work.
        for p in order:
            ticket = await breaker.acquire(p.name, self.redis)
            if ticket is None:
                continue
            try:
                agen = p.stream(prompt)
                first = await agen.__anext__()

                async def _wrapped(first_chunk=first, gen=agen, provider_name=p.name, lease=ticket):
                    try:
                        yield first_chunk
                        async for chunk in gen:
                            yield chunk
                    except Exception as error:
                        if breaker.transient(error):
                            await breaker.record_failure(provider_name, self.redis, lease)
                        raise
                    else:
                        await breaker.record_success(provider_name, self.redis, lease)
                    finally:
                        await gen.aclose()

                return p.name, _wrapped()
            except StopAsyncIteration:
                await breaker.record_success(p.name, self.redis, ticket)
                return p.name, _empty()
            except Exception as e:  # noqa: BLE001
                if breaker.transient(e):
                    await breaker.record_failure(p.name, self.redis, ticket)
                last_err = e
                continue
        raise RuntimeError("all providers unavailable") from last_err


async def _empty() -> AsyncIterator[str]:
    if False:
        yield ""  # pragma: no cover
