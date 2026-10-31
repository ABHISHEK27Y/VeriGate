# Research baseline and Phase 0 decision

**Checkout inspected:** `45fb5c0` on `codex/learning-guide`, then an isolated
`codex/evaluation-integrity` branch. The pre-existing untracked `audit/` directory was
left untouched. This record describes the code at that checkpoint; later results must
identify their own commit and configuration.

## What the current system actually does

| Area | Source | Confirmed behaviour and limit |
|---|---|---|
| API contract | [`app/schemas.py`](../app/schemas.py) | Stateless, single-turn prompt or one user message. Conversation history and other generation parameters are rejected rather than silently reused. |
| Default | [`app/config.py`](../app/config.py) | `CACHE_MATCH_MODE=exact`; semantic reuse must be enabled explicitly. |
| Namespace and storage | [`app/cache/namespace.py`](../app/cache/namespace.py), [`semantic_cache.py`](../app/cache/semantic_cache.py) | Tenant and configuration scoped. Redis is authoritative; in-process vectors are an index. TTL and eviction exist. |
| Retrieval | [`semantic_cache.py`](../app/cache/semantic_cache.py) | Nearest query vector, then density from nearby candidates. The old pair evaluator always supplied density zero and bypassed real retrieval. |
| Decision | [`policy.py`](../app/cache/policy.py), [`threshold.py`](../app/cache/threshold.py) | Hand-set query threshold plus query-only structural checks; optional question-to-question NLI. None checks that the stored **answer** is usable. Invalid non-finite similarity is now rejected. |
| Staleness | [`volatility.py`](../app/cache/volatility.py) | Keyword heuristic; small smoke controls cannot establish general precision or recall. |
| Provider and demo | [`app/providers/`](../app/providers/), [`demo_semantic.py`](../demo_semantic.py) | Mock output is explicitly marked. MiniLM embeddings are real. Paid provider behaviour was not rechecked in this phase. |
| Evaluation | [`evaluation/benchmark.py`](../evaluation/benchmark.py), [`run.py`](../evaluation/run.py) | Hand-authored query-pair fixture, selected during development. No cached-answer label, independent annotation, held-out split, realistic cache replay, or uncertainty interval. |

**Confirmed defects addressed in Phase 0:** `NaN` similarity could pass the old
`sim < threshold` comparison; empty acceptance was reported as perfect precision;
the same pairwise figure was described as workload savings and answer correctness.
**Methodology weaknesses:** no held-out selection, answer-specific labels, candidate
retrieval evaluation, or fair threshold tuning. **Documentation inaccuracies:** the
README and report made general claims from this small fixture and used stale test counts.
**Unverified:** real-provider quality, payment, large-cache performance, and formal risk.

## Related work checked against primary sources

| System | Cached/matched item | Decision and adaptation | Verification and error claim | Cost/latency and evaluation limit relevant here |
|---|---|---|---|---|
| [GPTCache source documentation](https://github.com/zilliztech/GPTCache/blob/main/examples/README.md) | Prompt embedding and stored response | Configurable similarity evaluator and threshold | Optional LLM verifier post-processor exists; it is incorrect to call this a threshold-only system | Its examples include a benchmark, but this project has not reproduced it. |
| [vCache, ICLR paper](https://arxiv.org/html/2502.03771v5) | Nearest prompt embedding and cached response | Online, cache-entry-specific sigmoid decision boundary | Explores by generating a response and comparing it with cached output; paper derives an error bound under explicit assumptions | Reports several benchmark distributions and exploration cost. VeriGate's heuristic is not equivalent to its method or guarantee. |
| [Krites paper](https://arxiv.org/html/2602.13165v2) | Static curated answer and dynamic cache entry | Threshold plus grey-zone trigger | Asynchronous LLM judge after a miss, then approved answer promotion | Studies judge overhead and critical-path latency in trace simulations. VeriGate has not reproduced this method. |
| VeriGate at baseline | Stored question and answer | Hand-set query-dependent threshold | Structural question checks; optional bidirectional question NLI | Small candidate-pair fixture; answer reusability, cost, and held-out risk unmeasured. |

These sources overlap substantially with the old “adaptive self-verifying cache”
novelty language. In particular, question-to-question NLI is not proof that a cached
answer remains correct. We will not claim that adaptive thresholds, verification, or
semantic caching were invented here.

## Narrow hypothesis for later phases

**Primary hypothesis (not yet tested):** On independently labelled, held-out
answer-reuse examples, a selective policy that considers the cached answer and invokes
costlier verification only for uncertain candidates can improve correct reuse at a
matched incorrect-reuse rate compared with a fairly tuned query-only threshold, after
accounting for verification latency.

**Secondary hypothesis:** Query-only labels overestimate answer-level safety in cases
where the stored response is incomplete, stale, or tied to a different context.

The next phase needs an answer-aware annotation guide and review queue before policy
training. Public paraphrase labels alone are not answer-reuse truth. If independent
review is unavailable, a pipeline can be built, but no final quality claim follows.

## Phase progress

- **Phase 0:** baseline, measurement terminology, fail-closed score handling, generated
  report table, and documentation corrections. Verification evidence is recorded in the
  Phase 0 commit summary.
- **Later phases:** data construction, held-out evaluation, learned policy, and risk
  control remain unimplemented and must be reviewed separately.
