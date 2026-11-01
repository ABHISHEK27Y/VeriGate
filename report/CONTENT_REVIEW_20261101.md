# Report content and visual review — 1 November 2026

Scope: report source and saved evidence, not a new runtime test or certification of every code path. Pending Claude implementation is intentionally excluded. The main narrative retains 37dc7a7 and the diagram/dashboard reconciliation uses 1cdb80a; experiments keep their own recorded revisions.

## Corrections
- Reconciled base Compose versus organization-demo configuration/model-cache mounts.
- Removed stale uncommitted-dashboard descriptions in implementation and testing.
- Corrected JSON storage/response ordering and distinguished exact identity checks from semantic suitability assessment.
- Added judge validation (FLAN 7/15; NLI 13/15; 168 unlabelled disagreements) and public-query pilot v1/v3 numerical-boundary results.
- Cross-checked stress counts against nq_song_stress_20261030_v3/REPORT.md; added the 30-hit/66-call/36-suspected-mismatch trade-off, non-binding semantic capacity limitation and paired-comparison caveat.
- Cross-checked applicability and bidirectional fixed-candidate counts against their FINDINGS.md files, fresh HTTP counts against results_forward_verified/summary.json, and archived test totals against evaluation/results/checks.json.
- Retained historical timings and denominators; no experiment was rerun and no accuracy percentage was invented.
- Added release-maintenance wording: future code/configuration changes do not rewrite past measurements.

## Visual and link verification
60 pages; 10 landscape pages. Dense request, generation and candidate workflows were rearranged horizontally. Organization, storage, deployment, lifecycle and sequence views use distinct visible palettes while retaining their notation. Fourier/New Century is retained, matching the supplied reference source's font family. All pages rendered and reviewed; no overfull-box, undefined-reference or final LaTeX warnings. PDF contains 147 links with zero out-of-range internal page destinations. External targets are syntactically checked and new repository paths checked against the recorded commit; network availability is not certified.

## Remaining release reconciliation
Current runtime changes, fresh final-commit test totals, production quality, paid-provider costs, privacy-classifier recall and organization-scale throughput remain unverified. The institutional title is preserved; cost efficiency is explicitly an objective, not a measured billing result. All historical tables are retained with their original limitations. A report review does not remove the model's known valid-reuse misses or ambiguous approvals.

## Second cross-verification pass
Inspected the recorded main.py lifespan and JSON/stream handlers, verifier prewarm and semantic-cache touch/read ordering at 1cdb80a. Corrected an overstatement: post-generation revocation suppresses storage but does not necessarily suppress delivery. Corrected the candidate-flow order to read/validate, then touch recency, then gateway authorization check; documented the remaining non-atomic mutation window. Startup failure labels now distinguish failure before serving from a running readiness response, and MiniLM warmup is conditional on the selected backend. Added the missing D3 admission-state read arrow and clarified data-flow labels. Recalculated the Redis-stage medians and RSS delta from raw saved arrays/bytes; values match the report. Checked frozen fixed-candidate and HTTP summary denominators. Verified cited vCache/Krites/GPTCache metadata against arXiv/ACL and made the arXiv references clickable in the bibliography. No new application tests or model-quality measurements were claimed.

## Current published layout

Historical layout notes above are superseded by the 60-page all-portrait
revision in PORTRAIT_UI_CHECKPOINT_20261101.md, the current visual-check record.
