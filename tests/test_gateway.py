"""End-to-end behaviour tests. Each test asserts one guarantee of the system."""
from conftest import HEADERS


def _chat(client, text):
    return client.post("/v1/chat", json={"prompt": text}, headers=HEADERS)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_required(client):
    r = client.post("/v1/chat", json={"prompt": "hi"})  # no key
    assert r.status_code == 401


def test_cache_miss_then_hit(client):
    r1 = _chat(client, "how do I reset my password")
    assert r1.json()["cache"] == "MISS"

    # A close paraphrase should HIT the cache.
    r2 = _chat(client, "how do I reset my password please")
    assert r2.json()["cache"] == "HIT"
    assert r2.json()["answer"] == r1.json()["answer"]  # same answer served


def test_verifier_rejects_number_mismatch(client):
    """The novelty in action: near-identical wording, different number -> verifier rejects.

    The two queries are similar enough to clear the similarity threshold (a candidate
    HIT), but the verifier catches the number mismatch and refuses to serve the wrong
    answer -- exactly the false-hit case a static-threshold cache gets wrong.
    """
    q5 = "please tell me the total monthly cost of the 5 gb data plan for a new user"
    q50 = "please tell me the total monthly cost of the 50 gb data plan for a new user"
    _chat(client, q5)
    body = _chat(client, q50).json()
    assert body["cache"] == "MISS"
    assert body["note"] and body["note"].startswith("verify_rejected")


def test_volatile_query_bypasses_cache(client):
    r1 = _chat(client, "what is the weather today")
    r2 = _chat(client, "what is the weather today")
    assert r1.json()["cache"] == "BYPASS"
    assert r2.json()["cache"] == "BYPASS"  # never cached


def test_rate_limit_returns_429(client):
    # capacity=5 in tests; the 6th rapid request should be throttled.
    codes = [_chat(client, f"unique query number {i}").status_code for i in range(8)]
    assert 429 in codes


def test_tenant_isolation(client):
    """Security: one tenant must NEVER be served another tenant's cached answer."""
    A = {"x-api-key": "demo-key-123"}
    B = {"x-api-key": "tenant-b-key"}
    q = {"prompt": "how do I reset my password"}

    assert client.post("/v1/chat", json=q, headers=A).json()["cache"] == "MISS"  # A caches it
    # B asks the identical question -> must be a MISS (B has its own empty cache)
    assert client.post("/v1/chat", json=q, headers=B).json()["cache"] == "MISS"
    # A asks again -> HIT from A's own cache
    assert client.post("/v1/chat", json=q, headers=A).json()["cache"] == "HIT"


def test_metrics_endpoint(client):
    _chat(client, "hello there")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"verigate_requests_total" in r.content
