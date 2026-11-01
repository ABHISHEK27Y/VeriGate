# VeriGate follow-up session handoff (2026-11-01)

Audit-remediation + evaluation-integrity follow-up. Implementation and report
work on a focused branch off the supplied checkpoint. Draft PR opened; not merged.

## Checkpoint and branch

- Base branch: `codex/evaluation-integrity`
- Starting checkpoint (verified present): `26f820d33fc01215b6196f61817411de36e1bcb9`
- Follow-up branch: `codex/evaluation-integrity-followup`
- Final commit: `e65358a47a57398725c99e53c73369d8cd9eabca`
- PR: ABHISHEK27Y/VeriGate #5 (draft, base `codex/evaluation-integrity`) — not merged.

## Commits (26f820d..HEAD)

| SHA | Scope | Summary |
|---|---|---|
| 29f5ac5 | runtime | Enable `controlled-eval` provider on the organization path (dev-only, secret-less, rejected in production) + regression test |
| d94abcf | runtime (UI) | Fix dashboard answer-source label (controlled fixture no longer shown as "generated") + opt-in browser regression |
| 8e45558 | CI + tooling | Execute opt-in browser + pinned-NLI contract tests in CI with fail-on-silent-skip; add `scripts/assert_junit_executed.py` + `scripts/demo_controlled_http.py` |
| b70b33b | CI data | Regenerate stale `checks.json`/`checks.tex` (303/7 → 339/13) — fixes exact-revision diff gate |
| 9ea4bf5 | test fix | Pin `redis_url=""` in controlled-eval tests so the Redis CI job stays isolated |
| 5137cbe | report | Reconcile testing/results chapters, add audit-fix section + screenshot, recompile PDF |
| e65358a | report | Add reproducible screenshot-capture script |

Report changes are committed separately from runtime changes.

## Environment and limitations of this sandbox

- Python 3.11 in CI; a local `.venv-work` on 3.13 for verification.
- `download.pytorch.org` and `huggingface.co` are **blocked** by the egress proxy,
  and no models are cached. Therefore the **real MiniLM/NLI semantic path and
  `evaluation.run` could not run locally**; torch was installed from PyPI (with its
  CUDA deps) only so `sentence_transformers` imports for test collection.
- Local browser tests used the pre-installed Chromium via
  `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` with `playwright==1.63.0`.
- TeX Live was installed via apt; the report compiles locally.

## Priority 1 — exact-revision CI

Exact revision `26f820d3` CI (run #68) **failed**: only the Tests job's
"Verify generated report tables" step, whose `git diff --exit-code` caught the
committed `evaluation/results/checks.json` (310/303/7) and
`report/generated/checks.tex` (303/7) lagging the real suite. Regenerated both
from the actual run; the other seven generated tables regenerate identically and
no frozen measurement was rewritten.

## Priority 2 — opt-in tests now execute in CI

Confirmed by log inspection that at `26f820d3` neither the Playwright browser test
nor the pinned-NLI contract test was enabled in any job (both skipped silently).
Added:
- NLI contract step in `test-with-redis` (after the real-model step warms the
  pinned revision), with a junit no-skip assertion.
- A dedicated `browser-regression` job (pinned Playwright + Chromium, flag set),
  also gating `deploy-check`.
- `scripts/assert_junit_executed.py` fails a job if a required test skips/errors/
  fails or runs fewer than expected.

## Verified finding — answer-source label (reproduced + fixed)

Reproduced over HTTP: a `controlled-eval` fixture response was labelled
"generated answer" and provenance was inferred from answer text. Fixed the
dashboard to classify strictly from returned provider metadata
("controlled evaluation fixture" / explicit mock placeholder / "cached answer"
without asserting origin / named real provider / "unavailable"); removed the
answer-text heuristic. Display-only — acceptance, routing, and cache identity
unchanged; JSON and streaming share the provider field. Proven by
`tests/test_dashboard_source_label.py`.

## Controlled HTTP demonstration (exact path)

`scripts/demo_controlled_http.py` boots a disposable controlled-eval gateway and
over real HTTP records: employee-A MISS → labelled answer stored under the
authorized workspace; authorized colleague shared HIT (served from cache);
isolated private and cross-organization requests; 403 on an unauthorized
workspace; a prompt absent from the controlled map → 502 with no cache write on
retry; and TTL expiry. This is the **exact shortcut** path with real labelled
answers; it is **not** the MiniLM/NLI semantic paraphrase path (models blocked
here; that path ran in CI) and not accuracy/cost/production evidence.

## Verification

### Local (follow-up branch, `.venv-work`)
- Default suite (fakeredis, hash, mock): **339 passed, 13 skipped** (`python -m pytest tests/ -q`).
- Browser regressions (both files, `VERIGATE_BROWSER_TEST=1`, pre-installed Chromium): **2 passed**.
- Reproduced the Redis-job env (real Redis + `VECTOR_BACKEND=redisearch CACHE_MATCH_MODE=semantic`): controlled-eval tests **pass** after the `redis_url=""` fix.
- `ruff check .` and `ruff format --check`: clean. `mypy app/ evaluation/ scripts/`: no new errors vs. the checkpoint (5 pre-existing env-difference warnings only; CI mypy passes).
- Report: `latexmk -pdf report.tex` → A4 portrait, **0 undefined references, 0 overfull hboxes**.

### Exact-commit GitHub CI (follow-up branch, `9ea4bf5`, run #71) — all jobs SUCCESS
- Tests (incl. generated-table diff gate) ✓; Lint & Typecheck ✓; Security Audit ✓; Docker Build ✓.
- Browser Dashboard Regression ✓ (executed, not skipped).
- Tests with Redis Stack ✓, including **Real MiniLM and NLI live HTTP benchmark** ✓ and **Pinned NLI transformation contract (must execute, not skip)** ✓ — the real-model contract genuinely ran and passed.
- Run link: https://github.com/ABHISHEK27Y/VeriGate/actions/runs/41313365409
- Run #72 (`e65358a`, report-only commit) was queued at handoff time; report changes do not touch code.

### Skips (default suite, 13)
Opt-in Redis Stack integration tests, 3 pinned-NLI contract tests, and 1 browser
test — all executed in their dedicated CI jobs, not silently dropped.

## Report reconciliation

- Corrected the test-count prose (303/7/310 → 339/13/352) in the Results and
  Testing chapters; updated the testing-layers UI/browser row.
- Added §"Follow-up Audit Fixes and Controlled HTTP Demonstration" with a wrapped
  screenshot (`report/figures/ui_controlled_source.png`) showing the corrected
  "controlled evaluation fixture" label; clearly bounded as exact-path, non-accuracy.
- Historical experiments, denominators, and frozen numbers were preserved; new
  results added separately.
- `report/report.pdf` recompiled: **61 physical pages** (60 numbered content +
  bibliography). The original was 60. The +1 page is the new audit-fix section and
  its figure. **Remedy if a hard 60-physical-page cap is required:** shorten that
  section's paragraph or drop the figure.

## Status classification

- **Implemented:** controlled-eval org provider (dev-only); dashboard source-label
  correction; CI execution of opt-in browser + NLI-contract tests with fail-on-skip;
  regenerated test-count artifacts; reproducible HTTP demo + screenshot tooling.
- **Locally verified:** default suite, browser regressions, controlled HTTP demo,
  lint/type, report compilation.
- **Exact-commit CI (verified green):** all jobs on `9ea4bf5`, including the real
  MiniLM/NLI benchmark and the pinned-NLI contract.
- **Not established here:** real-provider (paid) completion/billing; independent
  answer-level accuracy; production readiness; behaviour under a real TCP
  disconnect (the stream-abandonment test is a logical regression, not a socket test);
  F1/F4 verifier-quality research (needs independently reviewed labels — not started).

## Remaining work / suggestions
- Optionally shorten the new report section to return `report.pdf` to 60 physical pages.
- Consider `\input{generated/checks}` to render the (now-synced) test-count table in the report, if desired.
- F1/F4 verifier-quality diagnostic remains gated on trustworthy, independently
  reviewed answer-reuse labels.
