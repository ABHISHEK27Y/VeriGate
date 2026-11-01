# VeriGate implementation handoff

Implementation owner working from the verified audit (`docs/CLAUDE_REVIEW_37dc7a7.md`
§7) and ledger (`docs/CLAUDE_REVIEW_LEDGER.md`). This file is a living progress
record; it is updated after each completed fix.

- Branch: `codex/evaluation-integrity`
- Starting checkpoint: `1cdb80a78ebb8bd00a53cea42aa080a523af950e`
- Test venv: `.venv-local-demo` (has structlog + ML deps; `.venv` is missing structlog)
- Baseline before this work: **303 passed / 7 skipped** (fakeredis, hash embeddings)
- Report chat's files under `report/` are left untouched; only runtime/test/eval
  files are edited. Each commit stages only this owner's files.

## Rules being honored

- No report/ edits, no merges/deploys, no paid provider calls, no reset of the demo tenant.
- Superseded advice from review §§1–6 is not implemented; §7 corrections govern.
- No guarded early exit this pass (F18); batching/dedup treated as proposals to verify.
- No tuning on inspected/held-out cases.

## Progress log

### DONE — F8/F9: Redis clock for LRU + legacy eviction counter
- Commit: `5365d89`
- Files: `app/cache/storage.py`, `tests/test_scoped_capacity.py`
- Change: `touch` and the unscoped `put` now read the Redis server clock (shared
  `_clock_to_seconds` helper) so write and hit-touch recency use one source;
  the unscoped path now increments `{ns}:evictions:{tenant}`.
- Tests: `test_legacy_tenant_counts_lru_evictions`, `test_touch_uses_redis_clock_for_recency`;
  storage regressions (scoped_capacity, remediation, audit_regressions, hardening) pass.
- Invariants preserved: WATCH quota transactions, fail-closed limits, scoped path unchanged.

### DONE — F3: context-aware volatility
- Commit: `49133b6`
- Files: `app/cache/volatility.py`, `tests/test_freshness_rules.py`,
  `evaluation/dev/freshness_technical_holdout_v1.tsv`,
  `evaluation/runs/freshness_technical_holdout_20261101_v1/`
- Change: procedure/concept/compound rescues over value+recency words; absolute-time
  still bypasses (except SQL-construct time words).
- Evidence: dev set stable false bypass 6→2 (polysemy residuals), volatile 12/12;
  disjoint technical holdout 1/14 stable false bypass, 0/10 volatile missed (not tuned).
- Full suite after F3: **322 passed / 7 skipped**.

### DONE — lint cleanup for F8/F9 tests
- Commit: `8b4cdbf` (named constants in `tests/test_scoped_capacity.py`).

### DONE — F5/F6: verifier recovery + hashed too_long memo
- Commit: `cef78c8`
- Files: `app/cache/verifier.py`, `app/cache/reuse_verifier.py`, `tests/test_nli_input_bounds.py`
- Change: shared `ModelHealth` (permanent config/contract failure vs transient
  cooldown-then-retry); `too_long` memoized under a sha256 (scope, pair) key holding
  only the token count, bounded + purged per scope. Both NLI and reuse verifiers.
- Tests: ModelHealth transient-recovers/permanent-sticks, cooldown, too_long memo
  no-retokenize + hashed-key + per-scope purge, forced-unavailable recovery.
- Invariants: fail-closed while unavailable; readiness reports + clears failure category.

### DONE — F2: verifier token count + status in traces/metrics
- Commit: `29a2d85`
- Files: `app/cache/answer_policy.py`, `app/cache/semantic_cache.py`, `app/metrics.py`,
  `tests/test_answer_policy_live.py`
- Change: `AnswerDecision.input_tokens` threaded into each `candidate_trace` entry;
  `verifier_status` now distinguishes `too_long`; metrics
  `verigate_verifier_status_total{status}` + `verigate_verifier_input_tokens` (bounded).

### DONE — F7b: reuse lookup embedding on store
- Commit: `353ea77`
- Files: `app/cache/semantic_cache.py`, `app/main.py`, `tests/test_remediation.py`
- Change: `LookupResult.query_vector` (compare=False, repr=False) carries the miss
  embedding; `store(..., vec=)` reuses it when valid; threaded through `_cache_store`
  on both JSON and streaming paths. Test asserts one embed per miss.
- Full suite after F7b: **328 passed / 7 skipped**.

### DONE — F24: real-RediSearch cross-tenant isolation test
- Commit: `4a5e28a` (`tests/test_live_redis.py`). Verified passing against a disposable
  Redis Stack (port 6399): authorized shortlist excludes a closer-matching other-org /
  other-employee entry; every returned key is tenant-scoped.

### DONE — F13: NLI transformation-contract test
- Commit: `0d4eb5f` (`tests/test_nli_contract.py`, opt-in VERIGATE_NLI_CONTRACT_TEST=1).
  Verified against the real pinned model: predict() activation is torch.nn.Identity,
  predict == direct model logits, exactly one entailment label.

### DONE — F19: streaming stage timings
- Commit: `bc97ea8` (`app/main.py`, `tests/test_gateway_reliability.py`, `docs/ARCHITECTURE.md`).
  SSE meta now carries admission/provider/cache_write stages. latency_ms spans
  documented (not silently redefined).

### DONE — F16: semantic-without-artifact clarity
- Commits: `7eaab63` (startup warning + readiness `active_semantic_policy` + .env.example),
  `bd98d0b` (dashboard labels the Tier-1 structural fallback).

### DONE — F7c: ensure_index overhead
- Commit: `03e555d` (`app/cache/redisearch_store.py`, `tests/test_live_redis.py`).
  Validate-first; recreate only when absent. Recovery-after-drop + schema fail-closed
  verified on real Redis Stack.

### Integration evidence
- Full suite on real Redis Stack (disposable, port 6399): **338 passed / 4 skipped**
  (skips: 3 opt-in NLI contract + 1 browser). Default fakeredis suite: **330 passed / 11 skipped**.

### DONE — F14: breaker probe release on stream abandonment
- Commit: `c999a9b`. Reproduced the half-open probe leak on client disconnect; added
  `breaker.release_probe` called from `registry._wrapped` when the stream settles neither way.

### DONE — F17: labelled freshness contrast in the evaluator
- Commit: `ebd726b`. `evaluation.run` now reports dev-set (2/12) and holdout (1/14) stable
  false bypasses + volatile misses separately; smoke control retained.

### DONE — F20: matched-family paired stress bootstrap
- Commit: `d3c7ccd`. `evaluation/protocol.py:paired_family_bootstrap` + `scripts/paired_stress_analysis.py`.
  On v3 data (static − answer-aware): suspected-wrong/req +0.036 CI [0.003, 0.067] (excludes 0);
  correct/req +0.030 CI [-0.004, 0.064] (contains 0). Reported, not interpreted.

### DONE — F22: capacity-pressure experiment
- Commit: `dde96b0`. `scripts/measure_capacity_pressure.py` on real Redis: limit 20, 50
  distinct entries → 50 puts, 20 final, 30 evictions, oldest evicted, newest retained.

### DONE — mypy + lint cleanup
- Commit: `a1a7eb2`. `mypy app/ evaluation/ scripts/` clean (125 files).

### F23 — addressed by methodology, NO runtime change (per correction 1)
The generic mock echoes the prompt, which confounds the answer-aware NLI (the cached
answer contains the stored question). Per the correction, the mock is **not** changed to
a constant answer (that would manufacture hits). The correct applicability demonstration
uses the existing `ControlledEvaluationProvider` with explicit labelled answers:
set `LLM_PROVIDER=controlled-eval` and `EVALUATION_ANSWERS_PATH=<labelled map>` (dev only),
then: first miss → controlled labelled answer → eligible storage → authorized colleague's
paraphrase → genuine semantic decision, preserving negative examples. Do not put
evaluation answer maps into production policy. Generic-mock tests remain for transport/
completion/plumbing only. This is demonstration methodology (report/demo chat territory);
no gateway code changed.

### F1/F4 — research, deferred (offline, no deploy change)
Representation experiment and structural-guard narrowing require a fresh family-disjoint
frozen set and independently reviewed labels, which do not exist. The reuse-verifier
pipeline already uses a one-sided three-field input and enforces source/family-disjoint
splits + provenance gates; the bounded diagnostic in CLAUDE_REVIEW §7.7 can run offline
against the pinned model but must not drive a deployment change. Not started; not blocking.

---

## Final status

**18 commits on `codex/evaluation-integrity` (1cdb80a..HEAD), none touching `report/`.**

### F1–F24 matrix

| F | Title | Status | Evidence |
|---|---|---|---|
| F1 | Low valid reuse (verifier quality) | deferred (research) | needs labels; §7.7 experiment only |
| F2 | Token-window visibility | **fixed** | `29a2d85`; trace input_tokens + metrics; probe confirms |
| F3 | Over-broad volatility | **fixed** | `49133b6`; dev 6→2, holdout 1/14, volatile 12/12 |
| F4 | Structural guard recall | deferred (research) | needs frozen set first |
| F5 | Verifier latches unavailable | **fixed** | `cef78c8`; ModelHealth cooldown/recovery |
| F6 | Memo byte bound | **fixed** | `cef78c8`; hashed too_long memo, no raw text |
| F7a | Streaming coalescing | documented limitation | JSON-only retained (per correction) |
| F7b | Duplicate embed on store | **fixed** | `353ea77`; one embed per miss (test) |
| F7c | Per-write ensure_index | **fixed** | `03e555d`; validate-first, recovery verified |
| F8 | LRU clock mix | **fixed** | `5365d89`; Redis clock everywhere |
| F9 | Legacy eviction counter | **fixed** | `5365d89`; counted (test) |
| F10 | Workspace-scope validation | fixed by Soul (`1cdb80a`) | verified; ordering checked |
| F11 | Privacy restricts sharing | intentional tradeoff | no change |
| F12 | Profile/secret cache boundary | documented | readiness `active_semantic_policy`; ARCHITECTURE |
| F13 | Score-transform contract | **fixed (test)** | `0d4eb5f`; Identity activation verified on real model |
| F14 | Stream disconnect lease leak | **fixed** | `c999a9b`; reproduced + released |
| F15 | Dashboard timing label | fixed by Soul (`1cdb80a`) | verified |
| F16 | Semantic-without-artifact | **fixed** | `7eaab63`,`bd98d0b`; warning + readiness + UI |
| F17 | CI accuracy gate thin | **improved** | `ebd726b`; labelled contrasts reported |
| F18 | Shortlist early exit | NOT changed (correct) | early-exit withdrawn; dedup already via memo |
| F19 | API timing spans | **fixed** | `bc97ea8`; stream stages + docs; probe confirms |
| F20 | Paired stress analysis | **added** | `d3c7ccd`; paired bootstrap + real result |
| F21 | Trade-off framing | reported | §7.8/§F21 in review; paired result supports |
| F22 | Capacity pressure untested | **resolved** | `dde96b0`; real eviction evidence |
| F23 | Mock confound in demo | methodology (no runtime change) | controlled-answer recipe above |
| F24 | RediSearch isolation untested | **fixed (test)** | `4a5e28a`; passes on real Redis |

### Verification at final commit (`8ce0453`)
- **Default suite (fakeredis):** 332 passed, 12 skipped.
- **Real Redis Stack (disposable):** 340 passed, 4 skipped (3 opt-in NLI contract + 1 browser).
- **NLI contract (opt-in, real model):** 3 passed.
- **mypy app/ evaluation/ scripts/:** clean. **ruff check/format:** clean on all committed code
  (the only ruff errors are in the report chat's uncommitted `report/`, `tmp/` files).
- **Evidence validators** (verify_current_pilots, verify_applicability, verify_live_applicability,
  verify_live_combined, verify_bidirectional_answer, verify_evidence_bundle, verify_live_runs): all OK.
- **CI diff gate** (checks.json, report/generated/, RESULTS_DIRECTIONAL/ANSWER_AWARE): clean.
- **Fresh HTTP probe** (final code, real Redis, mock provider): readiness answer_aware + prewarmed;
  volatile bypass + technical-current cached; JSON and stream misses report full stages; trace has input_tokens.
- **Browser regression:** skipped here (Playwright/Chromium absent); runs in CI.

### Not done / limitations
- **F1/F4** (verifier quality, guard narrowing): research, need labels; not started.
- **F23**: methodology documented, no runtime change (by design).
- **Browser regression** not executed in this environment.
- **Real-provider** completion/usage unverified (no paid authorization) — unchanged.
- The default fakeredis suite does not exercise semantic/RediSearch/real-NLI; those are covered
  by the real-Redis run and opt-in contract test.

### Demonstration startup (unchanged)
```
powershell -File scripts/start_org_demo.ps1
```
Semantic + answer-policy + prewarm + mock org profiles; `/ready` now shows
`active_semantic_policy: answer_aware`. For a seeded shared hit, follow docs/ORG_WORKSPACE.md.

### Next concrete action
Run the browser regression and the opt-in NLI contract test in CI (both are wired and pass
where their deps exist), then decide on F1/F4 only once independently reviewed technical
labels are available.

## Final-checkpoint checklist (not yet run)
- Full local suite + real Redis Stack integration + browser regression + lint/type +
  evidence validators + a fresh isolated HTTP probe against the final code.
- Record final commit, F1–F24 matrix, before/after where comparable, demo command.
