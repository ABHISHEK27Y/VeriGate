# Security & Threat Model

A structured look at what can go wrong with VeriGate — now and in the future — and how to be
ready. Ordered by severity. Each item: **what**, **impact**, **mitigation**, **status**.

Legend for status: ✅ done · 🟡 partial · ⬜ planned (pre-deploy).

---

## Current posture (what already exists)
- API-key authentication on every request (401 without a valid key). ✅
- Secrets in `.env` only, git-ignored; keys never logged; provider keys read from env. ✅
- Token-bucket rate limiting per API key (Redis, atomic). ✅
- Input validation via Pydantic (rejects malformed bodies with 422). ✅
- Graceful degradation: provider failover to mock; cache fails open if Redis/vector errors. ✅
- Container runs as a non-root user; secrets not baked into the image. ✅

---

## CRITICAL

### 1. Cross-tenant cache leakage  ✅ (fixed)
**What:** a *global* semantic cache lets user B's question semantically match user A's cached
answer, so B receives A's answer — worse than an exact cache because "close" queries hit.
**Impact:** confidential data leakage across users; the single most serious risk for a caching
proxy.
**Mitigation (IMPLEMENTED):** the cache is now **partitioned per tenant**. `tenant_id =
"t_" + sha256(api_key)[:16]` (see `main._tenant`). The in-process index is a dict keyed by
tenant; Redis keys are `cache:ids:<tenant>` / `cache:entry:<tenant>:<id>`; the RediSearch
backend pre-filters KNN by a `tenant` TAG. Every lookup/store is scoped to the caller's tenant.
**Status:** ✅ verified by `tests/test_gateway.py::test_tenant_isolation` (in-process) and the
`redisearch_store.smoke_test()` isolation assertion (RediSearch). See RESULTS_LOG Phase 14.

### 2. Cache poisoning  ⬜
**What:** an attacker who can write to the cache seeds a malicious/incorrect answer that is
later served to others.
**Impact:** integrity loss; misinformation served as "cached".
**Mitigation:** only cache responses from trusted providers; per-tenant isolation (a poisoned
entry stays in the attacker's own partition); optional content validation; never cache from
untrusted/echo sources in production.
**Status:** ⬜ (mostly solved by #1 isolation).

### 3. Bill-shock / cost-exhaustion (economic DoS)  ✅ (fixed)
**What:** an attacker floods the gateway with **unique** queries → every one is a cache MISS →
every one hits the paid LLM. Your bill and rate limits both explode.
**Impact:** financial damage; provider quota exhaustion; outage.
**Mitigation (IMPLEMENTED):** per-key **daily spend budget** — `daily_request_budget` caps
PROVIDER calls per key per day in Redis (`app/budget.py`); over-budget requests get a 429.
**Cache hits are free and never counted, so the cache extends the budget.** Combined with the
existing token-bucket rate limiter. (Still open: a global spend cap + anomaly alerting.)
**Status:** ✅ per-key budget done + tested; global cap/alerting ⬜.

---

## HIGH

### 4. Prompt injection / jailbreak passthrough  ⬜
**What:** the gateway forwards user prompts to the LLM verbatim; malicious prompts can jailbreak
the model or exfiltrate system instructions.
**Impact:** harmful/policy-violating output attributed to your service.
**Mitigation:** optional input guardrail (injection/jailbreak detector — ties to the CyberShield
work), output moderation layer, system-prompt hardening. Make it a pluggable middleware.
**Status:** ⬜ (design hook exists; not implemented).

### 5. Sensitive data at rest (PII in cache/logs)  🟡
**What:** prompts and answers stored in Redis (the cache) may contain PII/secrets; logs may too.
**Impact:** privacy/compliance breach if Redis or logs are exposed.
**Mitigation:** encrypt Redis at rest + TLS in transit; short cache TTLs; PII detection/redaction
before caching; a "do-not-cache sensitive" classifier (extends the volatility detector);
configurable prompt logging (off by default in prod); data-retention policy.
**Status:** 🟡 volatility skip + no prompt logging by default; encryption/PII redaction ⬜.

### 6. Unauthenticated `/metrics` endpoint  ⬜
**What:** `/metrics` is currently public and exposes operational data (traffic, cache hit-rate,
per-key cost).
**Impact:** information disclosure aiding an attacker.
**Mitigation:** require an internal token / network policy for `/metrics`, or expose it only on a
private interface scraped by Prometheus.
**Status:** ⬜ quick pre-deploy fix.

### 7. Secrets management in production  🟡
**What:** `.env` files are fine for dev but risky in prod (accidental commit, image leakage).
**Impact:** leaked provider/gateway keys → abuse, cost.
**Mitigation:** use the host's secret manager (Render/Fly/Vault/SSM), rotate keys, least
privilege, alert on anomalous usage; keep `.env` git-ignored (done).
**Status:** 🟡 dev handling correct; prod secret store ⬜.

### 8. SSRF via provider base URL  🟡
**What:** provider `base_url` is config-driven; if it ever accepted untrusted input it could be
pointed at internal services.
**Impact:** server-side request forgery to internal metadata/services.
**Mitigation:** treat base URLs as trusted config only; allowlist hosts; never derive from
request data. (Currently config-only, so low risk — keep it that way.)
**Status:** 🟡 safe by construction today; document the invariant.

---

## MEDIUM

### 9. Adversarial false-hit induction  🟡
**What:** an attacker crafts queries near a victim's cached query to force a false hit (wrong
answer) or to probe the cache.
**Impact:** integrity/privacy.
**Mitigation:** the self-verifier (Tier-1/Tier-2) already rejects structural/semantic mismatches
(🟡); per-tenant isolation removes cross-victim probing (⬜ via #1).

### 10. Cache-timing side channel  ⬜
**What:** a HIT (fast) vs MISS (slow) reveals whether a query was already cached — across tenants
this leaks whether *someone else* asked something.
**Impact:** privacy inference.
**Mitigation:** per-tenant isolation makes it intra-tenant only (acceptable); for high-security
deployments, response-time normalization.
**Status:** ⬜ (mostly resolved by #1).

### 11. Denial via expensive Tier-2 NLI  🟡
**What:** if Tier-2 NLI runs on attacker-controlled candidate hits, an attacker could force many
expensive NLI evaluations.
**Impact:** CPU exhaustion.
**Mitigation:** Tier-2 is opt-in and should be gated to borderline similarities only; add a
per-request NLI budget.
**Status:** 🟡 opt-in; borderline-gating ⬜.

### 12. Unbounded cache growth (memory DoS)  ⬜
**What:** the cache grows without limit; the in-process matrix and Redis both consume memory.
**Impact:** OOM / degraded latency.
**Mitigation:** max-entries cap + LRU/LFU eviction; TTLs on entries; monitor memory.
**Status:** ⬜.

### 13. Transport security & HTTP headers  ⬜
**What:** no enforced TLS/HSTS/secure headers/CORS at the app layer.
**Impact:** MITM, XSS on any future dashboard, permissive CORS.
**Mitigation:** terminate TLS at the proxy (Caddy/Nginx/host), add HSTS + security headers,
restrict CORS to known origins, hide server banner.
**Status:** ⬜.

### 14. Dependency / supply-chain vulnerabilities  ⬜
**What:** third-party packages (FastAPI, Torch, redis, …) may have CVEs.
**Impact:** RCE/DoS via a vulnerable dependency.
**Mitigation:** pin versions (done for most), run `pip-audit`/Dependabot in CI, rebuild images
on advisories, use minimal base images.
**Status:** ⬜.

---

## LOW

### 15. Weak / shared API keys  🟡
Use long random keys, per-client keys, rotation, and per-IP limits alongside per-key. (Keys
exist; strength/rotation policy ⬜.)

### 16. Output safety  ⬜
LLM output may be harmful; add an output-moderation hook for user-facing deployments.

### 17. Verbose errors  🟡
Ensure production errors don't leak stack traces/internal detail to clients.

---

## Attacker's-eye summary (what to fix first before going public)
1. ~~**Isolate the cache per tenant** (#1/#2/#9/#10)~~ ✅ **DONE** (Phase 14) — the defining risk
   of a semantic cache, now fixed on both backends.
2. ~~**Add spend/quota budgets** (#3)~~ ✅ **DONE** (Phase 18) — per-key daily budget.
3. **Lock down `/metrics`** and move secrets to a real store (#6/#7).
4. **TLS + security headers + CORS** and dependency scanning (#13/#14).
5. **Cache size caps + TTLs** (#12) — ✅ TTL done (Phase 18); max-size eviction still ⬜.

These five turn the demo into something safe to expose. Everything else is hardening depth.
