# VeriGate — current major-project proposal

**Author:** Abhishek Yadav · **Program:** B.Tech CSE (AI/DS), IIIT Manipur
**Status:** working gateway and exploratory cache research; not production-ready.

## Problem

An LLM gateway can reuse a stored response to avoid another provider call. Exact reuse
is straightforward but misses reworded requests. Semantic reuse retrieves similar
questions, and similar questions can require different answers. A cache must decide
whether serving the **specific stored answer** is acceptable for the incoming request.

## What exists

VeriGate has a stateless FastAPI chat API, tenant-scoped Redis cache, rate limiting,
provider routing/failover, streaming, request-latency metrics, and mock-provider demos.
Exact-prompt matching is the default. The opt-in semantic path retrieves a vector
candidate, applies an adaptive threshold and conservative question-only checks, and can
optionally run question-to-question NLI. Keyword rules bypass some volatile queries.
None of these checks proves the stored answer is correct or fresh.

## Research question and proposed contribution

Can a small, interpretable **selective verification policy** decide when to accept,
reject or spend compute on verification, improving latency at comparable answer-reuse
quality against fairly tuned baselines? This is a hypothesis, not an established
novelty or successful result. Prior systems already use adaptive thresholds and
verification; see [related work](RESEARCH_BASELINE.md).

The intended decision unit is `(stored query, actual cached answer, incoming query,
tenant/context/version)`. The first bounded study is English factoid short answers.
Generated long answers, multi-turn conversations and changing facts require separate
validation. An independent answer-review set and frozen split are needed before a
defensible quality claim.

## Current evidence and limitations

- The original 30-pair smoke fixture is development evidence only.
- QQP/PAWS/STSB are question-pair proxies, not answer-reuse labels.
- A mined 11,586-pair NQ-Open corpus has symmetric reference-answer labels. An
  [audit](../evaluation/results/answer_label_audit.json) found 124 historical positive
  rows where the concrete stored answer is absent from incoming references. They need
  adjudication; string absence alone does not prove all are wrong.
- Five overlapping splits show a severe risk–coverage trade-off. The finite-grid
  selector chose reject-all for 1%, 2%, and 5% targets on that proxy. The local judge
  failed validation. No reviewed answer-level accuracy is available.
- Replay is simulated and local; provider monetary savings and production error rates
  have not been measured.

## Completion criteria

Freeze a reviewed dataset and split protocol, compare exact and fairly tuned semantic
baselines with a selective policy, measure latency and verifier calls, and show live and
offline agreement on the same trace. Preserve negative results. Report remaining
uncertainty and demonstrate a failure case, not only successful requests.

Read [phase status](PHASE_STATUS.md), [datasheet](DATASHEET.md), and
[experimental results](RESULTS_EXPERIMENTAL.md) for evidence. The original proposal is
[archived](archive/PROJECT_PROPOSAL_HISTORICAL.md) for provenance.
