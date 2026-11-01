# Diagram inventory and source trace

Checkpoint inspected for this correction pass: `1cdb80a78ebb8bd00a53cea42aa080a523af950e`. Only the code paths named below, the Compose file, and the Dockerfile were inspected for diagram behavior. Application code was not edited. Current uncommitted implementation work must be reconciled separately. All diagrams are editable standalone TikZ sources in `report/figures/`; `build_diagrams.py` compiles them without rewriting them and preserves `.log` files.

| Figure / purpose | Source and final location | Code basis / configuration | Abstraction or limit |
|---|---|---|---|
| 4.1 Actor goals | `figures/use_cases.tex`, Ch. 4 Â§4.2 | `app/main.py` chat, admin occupancy/clear, health and metrics routes | Goals only; does not show HTTP return as another use case. Implemented routes. |
| 4.2 Context DFD | `figures/dfd_context.tex`, Ch. 4 Â§4.3 | `app/main.py` client/admin routes; `app/providers/registry.py` provider boundary | External provider only for a real-provider profile; local mock and Redis remain internal. Implemented/configured variant. Replaces old compact context DFD. |
| 4.3 Level-1 DFD | `figures/dfd_level1.tex`, Ch. 4 Â§4.4 | `app/main.py` chat and operational handlers; `app/organization.py`; `app/cache/semantic_cache.py`; `app/cache/storage.py`; `app/cache/redisearch_store.py` | Logical D2 read/write symbol repeated for clarity; D2/D3 share Redis. Index overfetch and error exits omitted. Replaces old compact Level-1 DFD. |
| 4.4 JSON admission/lookup flow | `figures/request_flow.tex`, Ch. 4 Â§4.5 | `app/main.py` `chat`, `_bounded_lookup`, `_lookup_with_overlay`; `SemanticCache._lookup` | A/B connectors continue in 4.5. Streaming has a separate implementation. Replaces old compact request flow. |
| 4.5 JSON generation flow | `figures/generation_flow.tex`, Ch. 4 Â§4.6 | `app/main.py` `chat`, `_generate_answer`, `_cache_store`; `app/singleflight.py`; provider registry | Summarizes JSON leader/follower and response classification; stream cancellation not drawn. Implemented path. |
| 4.6 Candidate decision | `figures/candidate_decision.tex`, Ch. 4 Â§4.7 | `SemanticCache._lookup`; `app/cache/answer_policy.py`; `app/cache/verifier.py` | Optional technical/applicability guards are configuration dependent; experimental task verifier is not the normal path. Candidate action precedes aggregation. Replaces old assessment sketch. |
| 4.7 Semantic HIT sequence | `figures/hit_sequence.tex`, Ch. 4 Â§4.8 | `SemanticCache._lookup`, `redisearch_store.read_candidate`, `storage.touch`; gateway `chat` | Specifically after exact-key miss; final read and recency touch shown. No provider lifeline on a HIT. Implemented semantic profile. |
| 4.8 JSON MISS sequence | `figures/fallback_sequence.tex`, Ch. 4 Â§4.9 | `app/main.py` `chat`, `_generate_answer`, `_cache_store`; `ProviderRegistry.route_events`; `SingleFlight.run` | Fragments summarize failure/storage branches. No JSON coalescing promise for streaming or across workers. Implemented JSON path. |
| 4.9 Organization boundaries | `figures/organization_scope.tex`, Ch. 4 Â§4.10 | `app/organization.py` scope decision and opaque tenant identity; `app/main.py` private downgrade | Conceptual read/write rights; provider-profile compatibility explained in prose. Replaces old sharing sketch. |
| 4.10 Logical Redis design | `figures/storage_design.tex`, Ch. 4 Â§4.11 | `storage.keys`, `storage.put`, `storage.touch`; `redisearch_store.ensure_index`, `add`, `knn` | Redis hashes/sets/sorted sets, not SQL; process-local vector matrix is an alternative. Implemented RedisSearch profile. |
| 4.11 Deployment | `figures/deployment.tex`, Ch. 4 Â§4.12 | `docker-compose.yml`, `Dockerfile`, `ProviderRegistry`, `MockProvider` | Base Compose persists Redis `redis-data`; the illustrated organization-demo overlay additionally mounts read-only configuration and the model cache. External HTTP is conditional. Does not depict proposed scale-out as deployed. Replaces old deployment sketch. |
| 4.12 Startup and probes | `figures/startup_readiness.tex`, Ch. 4 Â§4.13 | `app/main.py` `lifespan`, `/live`, `/ready`, `/health`, `_health_details`; Dockerfile `HEALTHCHECK` | Conditional semantic warmup and RedisSearch schema checks; probe response detail varies by environment. Implemented startup. |
| 4.13 Cache residence | `figures/cache_lifecycle.tex`, Ch. 4 Â§4.13 | `storage.put`, `storage.touch`, `storage.clear`; `SemanticCache._lookup` final read | States separate TTL expiry, quota LRU, replacement, deletion and failed insertion. HIT touches recency, not TTL. Implemented storage path. |

The former inline architecture, sharing, assessment, request-flow, context, Level-1, cascade and deployment drawings in `4_System_Design.tex` were removed. The provider cascade remains in prose because its routing choices are not a separate system boundary and its quality effect is not established. No figure is retained solely to preserve page count. The institutional front matter and evaluation chapters remain structurally unchanged in this pass.

Final PDF page map (58-page build): Figures 4.1 and 4.2 appear on page 22; 4.3 on 24; 4.4 on 25; 4.5 on 27; 4.6 on 29; 4.7 on 31; 4.8 on 33; 4.9 on 34; 4.10 on 35; 4.11 on 36; 4.12 on 37; and 4.13 on 38.

## Visual and notation pass — 2026-11-01

Retained the recorded source checkpoint and evaluation results. Used the supplied reference report for visual clarity only. Applied a restrained navy/teal/amber palette with shape-based meaning preserved in monochrome. DFDs use Yourdon/DeMarco circles, external rectangles, parallel-line data stores and named data arrows. Sequence views use participant lifelines, activation bars, call/reply arrows and interaction fragments; control flows use labelled decision branches. The deployment view distinguishes execution environments, mounts and the external-provider boundary. Sharing and Redis-storage drawings are explicitly conceptual views, not relational ER diagrams.

Corrected the operations credential/cache flows, sequence frame spacing, optional-guard action connection and organization-demo mount depiction. Reviewed all 58 rendered pages, with enlarged checks of the sequence figures. No runtime code or evaluation measurements were changed. The PDF must still be reconciled against subsequent concurrent runtime commits before final submission.

## Superseding content/color pass
The latest report has 60 pages and ten landscape pages (24, 26, 28, 30, 32, 34, 35, 36, 37, 39). Earlier 58-page placement notes above refer to the prior build. See CONTENT_REVIEW_20261101.md for content corrections, evidence checks and PDF link validation.

## Current published layout

Historical layout notes above are superseded by the 60-page all-portrait
revision in PORTRAIT_UI_CHECKPOINT_20261101.md, the current visual-check record.
