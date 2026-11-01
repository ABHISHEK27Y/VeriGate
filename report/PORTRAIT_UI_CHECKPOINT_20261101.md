# Portrait report and dashboard checkpoint

## Report

The existing report was rebuilt as 60 A4 portrait pages. The prior version is
recoverable from `revision_backup_portrait_20261101` (diagram and chapter sources)
and earlier report backups. Editable TikZ sources remain in `figures/`.

Redrawn views: level-1 DFD, request/generation control flow, candidate assessment,
HIT/MISS sequence interactions, organization boundaries, Redis storage,
deployment and cache lifecycle. DFD transformations use circles, external entities
rectangles, and stores parallel lines. Control flow uses process rectangles,
decision diamonds and terminators. Sequence views group worker-local components
and use participant heads, lifelines and dashed replies. They are abstractions,
not a method-by-method execution trace.

Validation: compiled diagrams and report; rendered all 60 pages and reviewed
contact sheets plus individual changed diagrams. No overfull-box warnings or
unresolved references remained. All pages are portrait; 150 PDF links were
present and internal destinations were valid. Existing source checkpoints and
historical result denominators remain explicit. This visual pass does not
reconcile Claude's 19 runtime commits into the report or certify all current code.

## Dashboard

`app/static/dashboard.html` now has a glass-style layout with the request
workspace first, visible scope/retrieval/decision/delivery cards, candidate
evidence, NLI score, token count when returned, and actual stage timings.
Stage durations are explicitly non-additive. Unreported values are marked as
such. Cached text beginning with the mock marker is labelled accordingly;
matching known demo text is not treated as proof of source provenance.

The opt-in Playwright browser regression passed. Its forwarding fixture now
preserves Content-Type, matching the browser's actual JSON request. Normal
requests still omit scope overrides; developer-only and streaming behavior
remain covered. Local JSON and semantic HIT checks produced no browser script
errors, and the 390px viewport had no horizontal document overflow.

The running local container received only the HTML asset; gateway configuration,
model artifacts and Redis settings were not changed. A copy of the previous
container asset is in `tmp/ui/container-dashboard-before.html`. Rebuilding the
image is required to persist the edited source into a new image. No restart,
paid provider call, reset, merge or commit was performed.

Live checks used the configured organization mock provider and may have added
mock responses to the demo workspace. They are UI checks, not answer-quality or
latency benchmarks. Screenshots in `tmp/ui/dashboard-live-*.png` show real
responses with mock labels; do not use them as evidence of factual generation.
The current container did not return candidate token counts, so these display
as not reported. That is not proof the latest source lacks token instrumentation.
