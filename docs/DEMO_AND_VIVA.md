# Honest VeriGate demonstration and viva guide

This is a demonstration plan for the current prototype. Use `LLM_PROVIDER=mock`
and say that the answers are deterministic local examples. Do not call the
semantic path a proven answer-safety feature. The default `CACHE_MATCH_MODE=exact`
is the correct opening configuration.

## Ten-slide outline

1. **Problem:** repeated LLM requests cost time; approximate reuse risks returning
   the wrong stored answer.
2. **Contract:** one request, one stored response, one tenant and model/context version.
3. **Architecture:** client → FastAPI → tenant-scoped cache → selected provider.
4. **Exact path:** identical prompt reuses a response; explain TTL and cache namespace.
5. **Semantic path:** query-only baseline, then the separately opted-in answer-aware policy.
6. **Failure cases:** Austria/Australia, role swap, tense change and a valid password
   paraphrase that the conservative verifier rejects.
7. **Data:** QQP/PAWS pair proxies, NQ reference strings, the 124 discrepancy audit,
   and the 350-row model-judged queue. Show the separate diagnostic and random splits.
8. **Results:** [controlled comparison](RESULTS_ANSWER_AWARE.md): accepted 16/60,
   no observed incorrect accepts, and roughly 45 ms warm decision p50; show
   the 60-case denominator, two ambiguous cases, and the baseline failures.
9. **Related work:** GPTCache, vCache and Krites already use retrieval and forms of
   verification; define VeriGate's proposed bounded contribution.
10. **Limits and next gate:** authored cases, lexical hash retrieval, model
    opinion, limited latency scope, and independent transfer validation.

For the judge slide, open [the controlled diagnostic](AUTOMATED_JUDGE_RESULTS.md).
Explain why FLAN's zero positive predictions disqualify it as an acceptance
oracle, why NLI's 13/15 result is only preliminary, and why the two judges'
queue disagreements remain unresolved rather than converted into truth.

## Five-minute script

**0:00–0:40:** “VeriGate is a gateway in front of an LLM. Its normal cache mode is
exact. The research question is whether we can safely save additional calls by
reusing one stored answer for a reworded question.” Point at the request path.

**0:40–1:30:** Open `/ui`. Show matching mode `exact` in the configuration tiles.
Ask the same prompt twice with the mock provider. The first response is a MISS;
the second should be a HIT. Show the reason and latency. Explain that a hit
reuses the earlier provider reply, whether that reply was true or false.

**1:30–2:15:** Explain tenant isolation, TTL and the versioned namespace. Clear
the cache; the same request becomes a MISS. A different API key must not read
the first tenant's cached answer. Use the tests or a prepared trace if the UI
does not expose tenant identity.

**2:15–3:10:** Show `ANSWER_POLICY_ARTIFACT=app/cache/artifacts/answer_policy_v1.json`
alongside `CACHE_MATCH_MODE=semantic` as an optional local configuration.
Open [`AnswerPolicy.decide`](../app/cache/answer_policy.py) and trace the
stored question, exact cached answer, incoming question, and ACCEPT/VERIFY/REJECT
reason. Point to the live gateway and replay calls of this same method.

**3:10–4:00:** Open the [generated comparison](RESULTS_ANSWER_AWARE.md) and its
[saved decisions](../evaluation/runs/answer_aware_20261029_v6/decisions.csv).
Show one valid acceptance, one changed-fact rejection, one conflicting-answer
rejection, and an ambiguous VERIFY. Say that REJECT and VERIFY both ask the
provider in the gateway. Show 16/60 coverage and zero *observed* incorrect
accepts; never call that a zero-risk guarantee.

**4:00–5:00:** Show the cost: warm answer-aware decision p50 is about 45 ms
versus sub-millisecond query-only rules in this local run, with model loading
measured separately. State the negatives: FLAN failed validation, historical
risk control rejected all, and the new cases are authored rather than
representative traffic. The contribution is an opt-in answer-aware decision
path shared by live lookup and replay, plus a reproducible controlled comparison.

## Learn the code in this order

| Milestone | File and function | Small exercise | Viva question |
|---|---|---|---|
| 1. Request contract | [`app/schemas.py`](../app/schemas.py) request model | Send an invalid multi-turn request and inspect the response. | What inputs affect cache compatibility? |
| 2. Gateway flow | [`app/main.py`](../app/main.py) chat handler | Trace one MISS and one HIT using mock. | When is the upstream called? |
| 3. Cache store | [`app/cache/semantic_cache.py`](../app/cache/semantic_cache.py) `lookup`/`store` | Change a tenant key and compare outcomes. | Why isolate tenants? |
| 4. Versioning | [`app/cache/namespace.py`](../app/cache/namespace.py) `namespace` | Change `CACHE_EPOCH` and observe a MISS. | What invalidates old entries? |
| 5. Decision | [`app/cache/policy.py`](../app/cache/policy.py) `decide` | Compare the same pair with/without the verifier. | What does a threshold actually prove? |
| 5b. Answer policy | [`app/cache/answer_policy.py`](../app/cache/answer_policy.py) `decide` | Follow a conflicting-answer case to REJECT. | Why does NLI not prove factual truth? |
| 6. Structural check | [`app/cache/verifier.py`](../app/cache/verifier.py) `verify_equivalent` | Try present versus past tense. | Why can a strict rule reject a valid paraphrase? |
| 7. Labels | [`evaluation/gold_answers.py`](../evaluation/gold_answers.py) `cached_answer_reference_match` | Recreate the cast-list counterexample. | Why is the label directional? |
| 8. Replay | [`evaluation/stream.py`](../evaluation/stream.py) `replay` | Make two different queries share a vector. | Why must exact lookup ignore embeddings? |
| 9. Evidence | [`evaluation/protocol.py`](../evaluation/protocol.py) `metrics` | Calculate coverage and served-risk by hand from four rows. | What is risk when zero are accepted? |
| 10. Report | [`scripts/export_report_tables.py`](../scripts/export_report_tables.py) `main` | Trace one CSV cell into LaTeX. | How do you prevent a stale claim? |

Existing gateway, cache and baseline research predate this evidence-first revision.
This revision repairs concrete-answer labels, replay semantics and claims. The
implementation and writing were AI-assisted; the author must personally verify
the code, experiments and final interpretation before claiming the contribution.
