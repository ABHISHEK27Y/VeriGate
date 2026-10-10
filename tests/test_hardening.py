"""Production hardening: spend budget, circuit breaker, cache TTL cleanup."""

from __future__ import annotations

from conftest import HEADERS

from app import budget
from app.config import settings
from app.providers import breaker, registry
from app.providers.mock import FlakyProvider, MockProvider

HTTP_OK = 200
HTTP_TOO_MANY_REQUESTS = 429


# ---- spend budget ----
def test_budget_counter_blocks_over_limit(client):
    old = settings.daily_request_budget
    settings.daily_request_budget = 2
    try:
        assert client.portal.call(budget.check_and_count, "k1", client.app.state.redis) is True  # 1
        assert client.portal.call(budget.check_and_count, "k1", client.app.state.redis) is True  # 2
        assert (
            client.portal.call(budget.check_and_count, "k1", client.app.state.redis) is False
        )  # 3 -> over budget
        # a different key has its own budget
        assert client.portal.call(budget.check_and_count, "k2", client.app.state.redis) is True
    finally:
        settings.daily_request_budget = old


def test_budget_blocks_requests_but_hits_are_free(client):
    old = settings.daily_request_budget
    settings.daily_request_budget = 2
    try:
        h = HEADERS
        # 2 unique misses consume the budget; the 3rd unique miss is blocked (429)
        c1 = client.post("/v1/chat", json={"prompt": "budget one"}, headers=h).status_code
        c2 = client.post("/v1/chat", json={"prompt": "budget two"}, headers=h).status_code
        c3 = client.post("/v1/chat", json={"prompt": "budget three"}, headers=h).status_code
        assert c1 == HTTP_OK and c2 == HTTP_OK and c3 == HTTP_TOO_MANY_REQUESTS
        # a cache HIT does NOT consume budget (repeat of an already-cached query)
        hit = client.post("/v1/chat", json={"prompt": "budget one"}, headers=h)
        assert hit.status_code == HTTP_OK and hit.json()["cache"] == "HIT"
    finally:
        settings.daily_request_budget = old


# ---- circuit breaker ----
def test_circuit_breaker_opens_after_failures(client):
    old = settings.breaker_fail_threshold
    settings.breaker_fail_threshold = 3
    try:
        # Create a custom registry with flaky provider
        custom_registry = registry.ProviderRegistry(
            providers=(FlakyProvider(fail=True), MockProvider()),
            cascade=None,
            redis=client.app.state.redis,
        )
        # each call: flaky fails -> breaker records a failure -> mock answers
        for _ in range(4):
            name, _stream = client.portal.call(custom_registry.route_stream, "hi")
            assert name == "mock"  # failover always succeeds
        assert client.portal.call(
            breaker.is_open, "flaky", client.app.state.redis
        )  # breaker tripped for the flaky provider
    finally:
        settings.breaker_fail_threshold = old
        client.portal.call(breaker.record_success, "flaky", client.app.state.redis)


test_budget_blocks_requests_but_hits_are_free.config_overrides = {"daily_request_budget": 2}
