# Claude review ledger and implementation handoff

Last updated: 2026-11-01. Reviewed baseline: `37dc7a7400c1811cbf501d596d3535286ce81e17`.

## Purpose and ownership

Accumulate Claude's independent review findings, our checks and corrections, and acceptance criteria for one consolidated implementation prompt after the audit. This is a review record, not evidence that fixes have shipped. Soul/the active implementation chat owns runtime changes. Reconcile each item against its final commit before assigning implementation; concurrent working-tree changes can make a finding stale. Preserve existing work and evaluation artifacts.

Product scope remains an organization-aware LLM gateway: authorized employee sharing, isolated organizations/private scopes, semantic retrieval with answer-applicability assessment, provider fallback, bounded resources, and understandable UI. Exact matching remains an internal optimization. Do not turn the project into a chatbot or trade correctness for higher hit counts.

## Review sources

- Primary ongoing review: [CLAUDE_REVIEW_37dc7a7.md](CLAUDE_REVIEW_37dc7a7.md), now saved in this repository by Claude; latest inspected version contains F1–F22. Use this file for future updates, with the attachment references below retained as provenance. Findings remain claims to verify, not implementation instructions to execute blindly.

- Initial independent review and expanded F1–F14: user attachment `dbbaa1dc-1c84-4a8c-b830-11ab5927075e/Pasted text.txt`.
- F2/F3 corrections: user attachment `297342ee-689f-4439-b3f4-aed8ab5dd565/Pasted text.txt`.
- Dashboard re-review and F15: user-pasted Claude response, 2026-11-01.
- Our verification: targeted static reads of current runtime files, working-tree diff, and saved evaluation summaries. No new runtime/test results were produced for this ledger.

## Findings and planned treatment

| ID | Finding and evidence/status | Proposed treatment and acceptance criteria |
|---|---|---|
| F1 | Answer-applicability is the main valid-reuse bottleneck in inspected workloads. Saved fresh comparison: 6/15 baseline versus 8/15 combined; promotion gate not met. Other workloads must remain separate. | Evaluate an alternative verifier on fresh family-disjoint data with realistic answer lengths. Report valid reuse, incorrect accepts, ambiguous approvals, latency and resource costs separately. Do not lower thresholds on inspected cases or promote a failed gate. |
| F2 | Answer appears in both NLI assertions; saved long-answer case has 596 paired tokens against a 512-token window. Current code abstains safely. | Preserve full-input checks; expose token count/window/status in traces and bounded metrics. Evaluate a revised formulation or suitable model separately. Never silently truncate requirements. No universal character ceiling; measure actual paired tokens. Exact reuse is not ruled out by this semantic-verifier limitation. |
| F3 | Broad volatility rules bypass technical uses such as current user/live reload. Saved authored set: 6/12 stable and 12/12 volatile bypassed. | Distinguish procedure/concept requests from changing-value requests with contrastive cases. Preserve cases such as Bitcoin price without requiring explicit today/now. Words including now can occur in stable syntax explanations; unconditional word lists are not a complete solution. Freeze fresh validation separately from inspected development cases. |
| F4 | Scope and question-type guards can reduce recall. Claude proposes narrowing them. | First check answer applicability, not just wording. Most reliable versus reliable and only way versus a way are not universally equivalent. Test genuine paraphrases alongside changed constraints, quantities, ordering and yes/no/procedure mismatches. Do not broadly remove guards. |
| F5 | Current NLI code does not memoize too_long and permanently latches unavailable after an exception. Claude reports analogous task-verifier behavior; recheck that path before editing. | Add bounded negative-result memoization and controlled recovery/backoff for recoverable failures. Preserve fail-closed decisions and diagnostics. Test repeated oversized input, cooldown, successful recovery and concurrent retries. Avoid retry storms and endless retries for incompatible artifacts. |
| F6 | Memo uses raw text keys and an entry-count cap. Claude's approximate 1 GB scenario is not demonstrated: oversized pairs currently return before memo insertion. | Use bounded hashed keys and/or byte accounting, retaining scope and model/config identity. If F5 adds negative caching, do not retain oversized raw strings. Verify eviction, scope purge and memory bounds. Model RSS delta is process-level, not isolated weight size. |
| F7 | Duplicate semantic embedding on lookup/store, per-write RedisSearch ensure_index, and in-process index invalidation are present. JSON coalescing does not cover streaming. | Reuse compatible request vectors; optimize index setup with recovery behavior preserved. Do not blindly replace invalidation with append: cover replacements, eviction, expiry and cross-worker versions. Benchmark matched workloads. Treat streaming coalescing as separate work with isolation, cancellation, bounded buffering and terminal-event tests. |
| F8 | Scoped writes use Redis time while touch uses application time for LRU. | Use one authoritative clock consistently. Test skew and eviction order, including legacy paths as applicable. |
| F9 | Claude reports legacy eviction counter is not incremented. | Reconfirm the full legacy path; update occupancy accounting and test actual eviction counts without changing quota behavior. |
| F10 | Schema permits explicit workspace scope without workspace ID; resolution may fall back privately. | Define and validate explicit-override semantics. Reject incomplete explicit overrides if an ID is required; preserve automatic server scope resolution when override is omitted. Test both paths. |
| F11 | Conservative privacy patterns restrict some ordinary technical sharing. This is a tradeoff, not proof of a leak. | Add contrasting private/no-store/shared technical examples. Do not weaken privacy merely to raise hits or choose only favorable demo prompts. Document heuristic limits; authorization alone is not comprehensive DLP. |
| F12 | Claude reports profile compatibility and provider-secret rotation partition cache scopes. | Recheck derivation and document the boundary. Any redesign must consider provider/account compatibility, revocation and migration; do not remove isolation dimensions casually. |
| F13 | Potential score-transformation dependency risk; not a reproduced double-softmax bug. | Test raw-logit/activation/label mapping contract directly for the pinned library/model. Keep semantic model-quality tests separate: a correct transform does not guarantee a paraphrase exceeds a threshold. |
| F14 | Suspected early streaming-disconnect resource/lease leak; not reproduced. | Trace ownership and add a disconnect regression before fixing. Check upstream closure, cancellation, breaker lease release, no partial cache write, and bounded cleanup. |
| F15 | Confirmed UI label: total gateway time is populated from JSON latency_ms, whose timer begins after auth/rate limiting. | Relabel with the actual boundary and show browser HTTP duration separately. Do not silently redefine historical timing metrics. Streaming starts its timer earlier, so document endpoint differences. Check rendered labels and measurement boundaries. |

## Dashboard review checkpoint

## Additional findings F16–F22 (2026-11-01)

Checked the current candidate loop, token-diff guard, evaluation runner, stress analyzer, saved aggregate CSV, historical ablation/latency artifacts, and uncommitted streaming metadata diff. No application or evaluation runs performed. HEAD remains 37dc7a7; main.py now has uncommitted streaming metadata additions. Report expansion is concurrently underway and remains untouched by this review.

| ID | Assessment | Safe implementation/evaluation direction |
|---|---|---|
| F16 | Historical Tier-1 fixture accepted 0/30 pairs, including 0/15 positives. Token-diff guard rejects changed content tokens. This does NOT prove all non-exact inputs always miss: changes involving permitted function words can survive. | Expose active policy distinctly from semantic retrieval mode, document conservative historical behavior, and make demo configuration reproducible. Do not claim semantic retrieval without an artifact is intrinsically exact-only or alter rules merely to improve this inspected fixture. |
| F17 | evaluation/run.py uses the authored 15-positive/15-negative fixture and four stable controls; its threshold sweep is development analysis. | Retain this as a smoke/regression fixture, not an independent accuracy gate. Add meaningful freshness contrast cases and a separately frozen validation set. Version regenerated artifacts; do not overwrite historical evidence to conceal failed outcomes. Reconcile report placement because the table has moved to an appendix during report revision. |
| F18 | Loop evaluates multiple candidates after ACCEPT to detect conflicting accepted answers; saved historical NLI p50 is about 365 ms. The 800 ms provider reference in latency.py is assumed, not measured. | REJECT Claude's first-ACCEPT early-exit recommendation as an equivalent fix: lower-ranked conflicting answers would become invisible, and the current verification-limit semantics would also change. Any new stopping policy requires explicit semantics and evaluation. Optimize redundant work/memoization first. Do not multiply stage percentiles to claim a measured request percentile or infer current costs from mixed historical runs. |
| F19 | Uncommitted SSE metadata exposes latency_ms timed from handler entry, while JSON starts after authentication/rate limiting; SSE stage fields only contain lookup stages. | Define shared, explicit timing boundaries and document/version any change to existing metric meaning. Keep handler time, browser completion and streaming first-token/complete time distinct. Even moving the JSON timer does not include pre-handler middleware or network transfer. Stage timings may be nested, so they need not sum to total. Test controlled delays and omitted stages. |
| F20 | Stress analyzer reports family-cluster marginal intervals, not paired treatment-difference intervals. | Add a matched-family bootstrap that samples the same family IDs for both arms and reports the difference with clear denominators. Interval overlap alone proves neither significance nor non-significance; do not predict the paired result in advance. Statistical intervals still do not resolve authored-label errors. |
| F21 | Saved sufficient-capacity rows confirm static: 712 reference-matching hits, 90 suspected wrong hits, 198 provider calls; answer-aware: 682, 54, 264. Warm p50: 63.894 versus 211.609 ms under this controlled setup. | Present the observed trade-off: 36 fewer suspected wrong hits, 30 fewer reference-matching hits, 66 additional provider calls, approximately 147.7 ms higher median. This can improve an error-sensitive objective but is not an across-the-board performance gain. Do not describe 682/1000 as factual accuracy or claim that verification cannot improve a cache in any sense. |
| F22 | Saved semantic arms have 183/249 cache-write-stage observations, below cap 256; reported eviction/expiry misses are zero and outcome counts match the sufficient-capacity arm. This does not demonstrate semantic behavior under capacity pressure. | Create a separately versioned workload/capacity experiment with known initial occupancy and enough distinct eligible entries to trigger actual eviction. Record successful writes, peak occupancy, eviction counters and TTL behavior; a write-stage observation is not itself proof of successful insertion. Require eviction evidence, not necessarily a later eviction-caused miss, because future access order determines misses. |

These findings refine the master prompt; the raw review's 20-item prompt must not be pasted unchanged. In particular, its first-ACCEPT shortcut conflicts with preserving current conflict checks. No implementation is marked complete here.

## Dashboard review checkpoint (continued)

Claude found the uncommitted UI changes remove the hidden private example override and restrict manual overrides to an explicit developer demo. Our targeted inspection found tests asserting ordinary payload equality and a separate developer path. This is code/test inspection, not a fresh browser-test pass or committed release claim.

Keep automatic scope resolution in the normal flow. Present actual lookup/storage scope and answer source truthfully. Showing candidate justification expanded in presentation mode is a UX suggestion, not a backend correctness fix. Do not label mock placeholders as factual provider answers.

## Corrections and reporting boundaries

- Zero errors in five trials has an exact one-sided 95% binomial upper bound of approximately 45.1%, not 52%; tiny authored samples cannot establish production safety.
- Claude's old ~900-character ceiling remains stale in one table. Neither that nor the revised ~1,350-character extrapolation is a general model limit.
- Scope-key isolation is real engineering, but no leakage is too absolute when content classification is heuristic and all disclosure surfaces have not been exhaustively verified.
- Saved technical applicability labels support bounded controlled comparisons, not independently established general factual accuracy.
- Cost reduction is a product objective with a break-even condition; controlled-provider call counts are not measured monetary savings.
- Adaptive threshold and answer-policy paths must not be described as simultaneously active unless code actually composes them.
- Report revisions remain tied to their recorded snapshot until final implementation reconciliation.

## Consolidated implementation order

### Handoff reconciliation at 1cdb80a (2026-11-01)

Soul committed `1cdb80a78ebb8bd00a53cea42aa080a523af950e`. Verified commit diff: automatic normal-dashboard payload, developer-only overrides, streaming decision metadata, incomplete explicit workspace rejection and timing-label corrections. F10 and F15 are resolved in code; F19's API span inconsistency remains. Soul reports exact-commit CI success and local/Redis/browser passes; this ledger's review did not independently rerun those checks or fetch CI. The saved release HTTP observations explicitly describe a 37dc7a7 gateway image, not a full final-SHA integration run.

Claude's section 7 supersedes several earlier recommendations: first-ACCEPT exit and naive index append withdrawn; F16 universal reject-all claim corrected; F20 statistical prediction withdrawn; F22 capacity binding marked unresolved. Read section 7 together with the older findings.

- F23: mock output echoes the prompt; the release probe shows one seeded-answer accept and one mock-answer rejection. This is a demonstration/evaluation confound, not proof that echoing caused every paraphrase failure or that removing it fixes verification. Do not replace mock output with a universal response to manufacture hits. Use explicit, labelled controlled answers for suitability experiments; keep generic mock output visibly synthetic. A matched comparison holding questions and configuration fixed is needed to isolate representation effects.
- F24: Claude identifies a RediSearch cross-tenant automated-test gap. Add a real shared-index regression with unauthorized candidates closer than the eligible candidate, multiple scopes/organizations, and actual TAG-filter behavior. Keep existing in-process coverage. Distinguish missing automated coverage from a demonstrated leak.
- Batching/deduplication are candidates for optimization, not proven exact equivalence: padding/numerical differences, per-input token checks, memo state, gate ownership, deadline exhaustion and cancellation can change outcomes. Preserve conflict/limit behavior and assess score-boundary stability. The proposed same-answer early exit also changes timeout observability and requires explicit review rather than being called identical behavior.
- A raw-logit contract should use explicit activation configuration or comparison with direct model logits, not infer logits solely because values do not sum to one: raw logits can coincidentally satisfy that condition.

User now requests Claude as implementation owner. The report chat remains separate; protect its ongoing edits. Consolidated implementation prompt should fix bounded engineering defects first and keep verifier-quality work gated and separately evaluated.

1. Re-record branch/HEAD/diff and mark already-fixed findings with exact evidence. Do not overwrite ongoing work.
2. Fix bounded engineering defects: freshness behavior, verifier recovery/memo observability, clocks, accounting and override validation.
3. Optimize redundant work with consistency and isolation regressions; measure rather than assume latency improvement.
4. Reproduce suspected model-contract and streaming-lifecycle risks; fix only demonstrated problems.
5. Conduct the separate verifier-quality experiment and retain current defaults if promotion criteria fail.
6. Align UI, operational docs and report with the final configuration and measured results.

For each completed item record: changed files, mechanism, regression evidence, exact commit, residual limitation, and independent re-review status. Future Claude findings extend this ledger; they do not automatically authorize implementation or establish a fix.
