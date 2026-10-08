"""Production hardening: spend budget, circuit breaker, cache TTL cleanup."""
import asyncio

from app import budget
from app.config import settings
from app.providers import breaker, registry
from app.providers.mock import FlakyProvider, MockProvider
from conftest import HEADERS


# ---- spend budget ----
def test_budget_counter_blocks_over_limit(client):
    old = settings.daily_request_budget
    settings.daily_request_budget = 2
    try:
        assert budget.check_and_count("k1") is True    # 1
        assert budget.check_and_count("k1") is True     # 2
        assert budget.check_and_count("k1") is False    # 3 -> over budget
        # a different key has its own budget
        assert budget.check_and_count("k2") is True
    finally:
        settings.daily_request_budget = old


def test_budget_blocks_requests_but_hits_are_free(client):
    old = settings.daily_request_budget
    settings.daily_request_budget = 2
    try:
        H = HEADERS
        # 2 unique misses consume the budget; the 3rd unique miss is blocked (429)
        c1 = client.post("/v1/chat", json={"prompt": "budget one"}, headers=H).status_code
        c2 = client.post("/v1/chat", json={"prompt": "budget two"}, headers=H).status_code
        c3 = client.post("/v1/chat", json={"prompt": "budget three"}, headers=H).status_code
        assert c1 == 200 and c2 == 200 and c3 == 429
        # a cache HIT does NOT consume budget (repeat of an already-cached query)
        hit = client.post("/v1/chat", json={"prompt": "budget one"}, headers=H)
        assert hit.status_code == 200 and hit.json()["cache"] == "HIT"
    finally:
        settings.daily_request_budget = old


# ---- circuit breaker ----
def test_circuit_breaker_opens_after_failures(client):
    old = settings.breaker_fail_threshold
    settings.breaker_fail_threshold = 3
    try:
        registry.set_cascade(None, None)
        registry.set_providers([FlakyProvider(fail=True), MockProvider()])
        # each call: flaky fails -> breaker records a failure -> mock answers
        for _ in range(4):
            name, _stream = asyncio.run(registry.route_stream("hi"))
            assert name == "mock"          # failover always succeeds
        assert breaker.is_open("flaky")     # breaker tripped for the flaky provider
    finally:
        settings.breaker_fail_threshold = old
        breaker.record_success("flaky")
        registry.set_providers(registry.build_from_settings())
