# VeriGate: next implementation session

## Start here

Repository: ABHISHEK27Y/VeriGate. Base branch: `codex/evaluation-integrity`, not
`main`. The user will provide the exact pushed checkpoint. Fetch, record HEAD,
branch, status and available tools before doing work. Confirm that checkpoint is
present. If this environment cannot write files, execute tests or create a PR,
state that immediately; never present read-only connector access as implementation.
Create a focused follow-up branch from the supplied checkpoint if supported.
Do not reset, overwrite or force-push existing work. No automatic merge.

Read these files in order:
1. `docs/IMPLEMENTATION_HANDOFF.md`: completed runtime fixes and F1–F24 matrix.
2. `docs/CLAUDE_REVIEW_37dc7a7.md`: historical audit; later corrections supersede
   earlier recommendations. Findings are not automatically current defects.
3. `docs/CLAUDE_REVIEW_LEDGER.md`: reconciliation and constraints.
4. `report/PORTRAIT_UI_CHECKPOINT_20261101.md`: current UI/report boundaries.
5. `docs/ORG_WORKSPACE.md`, `docs/ARCHITECTURE.md`, applicable repository guidance,
   dependency locks and CI workflows.

Runtime implementation ended at `a1a7eb2`; probe evidence is at `8ce0453`, and
the completed handoff is `02f13c3`. Nineteen commits followed `1cdb80a` including
the handoff. The handoff's older 18-commit wording excludes its final commit.
Later commits add the dashboard and report; they do not replace that evidence.

## Product and boundaries

Improve the existing organization-aware, answer-aware semantic LLM gateway.
It serves integrated technical applications, not an ordinary ChatGPT session
interceptor and not a new chatbot. Distinct employee gateway credentials resolve
server-side organization, subject, application, permissions and provider profile.
Eligible answers can be shared across authorized colleagues in a compatible
workspace. Private responses remain scoped; unknown content must not be made
shareable merely to improve hit rate. No cross-organization reuse.

Keep the exact shortcut internally. Preserve semantic retrieval and bounded
answer assessment, final candidate identity checks, deadlines, quota accounting,
provider compatibility and fail-closed behavior. Normal UI requests should not
ask employees to select private/workspace scopes. Developer overrides remain
explicit and gated. Do not infer upstream secrets from gateway keys or browser
subscriptions; configured provider credentials stay server-side.

No new database migration, authentication platform, model download, provider
subscription or broad architecture rewrite is required for this session. Do not
make paid calls or change deployment defaults without explicit authorization.
Do not edit the academic report during implementation. Preserve frozen evidence.

## Priority 1: make the current checkpoint reproducibly verifiable

1. Inspect exact-revision CI. Distinguish passed, failed, pending and skipped.
   Fix concrete failures in separate, focused changes. Do not suppress evidence
   validators or rewrite frozen numbers merely to make CI green.
2. Check whether CI actually enables the opt-in Playwright dashboard test and
   pinned NLI transformation-contract test. Existing test files alone do not
   demonstrate execution. Add appropriately bounded jobs/steps if missing:
   install browser/dependencies, set required flags, retain failure artifacts,
   and fail the intended job if its required test silently skips. Keep ordinary
   lightweight jobs independent. Pin model revision and use caches; document
   unavailable network/model dependencies honestly. Do not update locked runtime
   packages wholesale to add a test dependency.
3. Run the relevant existing suites and validators using documented commands.
   Use disposable Redis and isolated namespaces; never flush the user's demo.
   Add regression tests only for concrete fixes or previously untested critical
   boundaries. Record exact commands, environment and skips.

## Priority 2: produce an honest end-to-end semantic demonstration

The latest UI is glass styled and displays returned scope, candidate actions,
NLI score, token counts when present, storage and stage timings. Preserve this
layout. It has been tested against a local container, but that container was not
rebuilt with all nineteen runtime commits. HTML alone was copied into it. A
GitHub checkout does not contain that container, downloaded models or secrets.

1. Build a disposable stack from the current source. Verify readiness identifies
   actual policy, model, vector backend and provider. Use the controlled-answer
   development provider already documented in IMPLEMENTATION_HANDOFF, with a
   small explicitly labelled answer map. Keep answer maps outside production
   decision logic. Do not convert the generic mock to a constant answer.
2. Demonstrate through actual HTTP: employee A MISS -> completed eligible answer
   stored -> authorized colleague's paraphrase -> candidate decisions and HIT or
   honest abstention; changed subject/action/version -> rejection or abstention;
   private isolation; cross-organization isolation; TTL expiry and a provider
   failure with no incomplete cache write. Maintain negative examples.
3. Use varied question wording, not just repeats. Show a real semantic decision
   trace with similarity, action/reason, verifier status, token count where
   available, provider invocation, storage outcome and timing. Inspect JSON and
   streaming separately; their timer spans differ. Do not sum nested stages or
   label NLI scores as calibrated correctness probabilities.
4. Save compact reproducible evidence with source/config/model identities and
   labelled screenshots. No hardcoded HIT responses, invented timing, fabricated
   provider answers or unsupported claim that all questions work.

## Priority 3: remaining product issues, only when demonstrated

Recheck current code and tests for authorization/cache-boundary regressions,
stale or mutated candidates at serve time, cancellation cleanup, verifier
recovery and long-input handling, embedding reuse on store, index recovery,
capacity accounting, and multi-candidate conflict/abstention behavior. Most of
these already have fixes: reproduce a remaining defect before changing them.

If profiling identifies redundant inference, tokenization or Redis round-trips,
make a small measured optimization with the same policy behavior. Preserve
scope/model/policy identities in memo keys, deadline semantics and conflict
checks. Do not return on the first ACCEPT simply to lower latency. Do not change
thresholds to turn inspected misses into hits. Compare warm/cold states and
retrieval, verification, provider and complete-request time separately. Controlled
or mock timing is not external-provider performance or monetary savings.

## Optional research: F1/F4 remain open

Known valid reuse losses and ambiguous/incorrect accepts remain the principal
answer-quality limitation. A larger embedder is not automatically the remedy:
retrieval can find the suitable answer while NLI still rejects it. Inspect saved
failure traces to identify the failing stage before proposing a model change.

If time remains, run one bounded offline verifier diagnostic using existing
tools and explicit download/memory/runtime limits. Preserve the baseline. Use
disjoint development and frozen evaluation families, independently reviewed
answer-reuse labels, negative examples, ambiguity, long answers and code-heavy
inputs. Authored or model-generated labels are provisional, not independent
truth. If trustworthy labels are unavailable, implement reproducible evaluation
plumbing or the diagnostic only; do not claim validation or promote a verifier.
Any future promotion must have predeclared valid-reuse, incorrect-acceptance,
abstention, latency and memory gates. Fewer false accepts on a small authored
set is not a universal correctness guarantee.

## Deliverable and stopping rule

Prioritize an executable checkpoint over another broad audit. Work in small
commits with relevant verification. Open a focused PR against
`codex/evaluation-integrity` when supported; do not merge it. If the integration
is read-only, give exact actionable findings rather than pretending to commit.

Before the session limit, save a concise progress record: base/final SHA, changed
files, reproduced defects and fixes, commands/results/skips, CI link/status for
the exact SHA, demo provider and evidence paths, and remaining work with reasons.
Clearly separate implemented, verified, experimentally evaluated and deferred.
Do not claim production readiness, cost savings or independent answer accuracy
without the necessary evidence. Leave report reconciliation for its own session.
