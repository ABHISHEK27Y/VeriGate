# Realistic-query pilot: NQ-Open dev with MiniLM

This is a **descriptive, unlabelled pilot**. It measures candidate selection, policy
decisions, and warm local latency. It does not measure answer correctness or a
production error rate.

## Reproduce and inspect

The [freeze](../evaluation/pilot_freeze_nq_dev_v1.json) was written before the
run. The immutable [manifest](../evaluation/runs/nq_dev_minilm_pilot_v1/manifest.json)
records the input and output hashes, model revisions, and local environment.
The [row-level decisions](../evaluation/runs/nq_dev_minilm_pilot_v1/decisions.csv)
and [aggregate metrics](../evaluation/runs/nq_dev_minilm_pilot_v1/metrics.csv)
are the numerical source for this page.

1. Download the [official NQ-Open original dev split](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open)
   to `data/NQ-open.dev.jsonl`. The source is [CC BY-SA 3.0](https://github.com/google-research-datasets/natural-questions/blob/master/nq_open/README.md).
   Cite Kwiatkowski et al. (2019) and Lee et al. (2019) when using NQ-Open.
2. Confirm its SHA-256 is
   `f15567f38099f3615f5b8a685c0aef449c11ad90d3da3735e8d1b98115b40616`.
3. Run `EMBEDDING_BACKEND=minilm python -m scripts.run_realistic_query_pilot <new_run_id>`
   from the repository root. The script refuses a changed source or policy artifact
   and will not overwrite an existing run directory.

The deterministic selection sorts normalized dev questions by SHA-256 of
`pilot-v1:<question>`, removes duplicate questions and overlap with both authored
controlled sets and the mined NQ train pairs, and takes 60 stored questions plus
50 distinct incoming questions. It adds 10 exact repeats of stored questions.
Each incoming question is paired with its nearest stored question under pinned
`all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
The cached answer is the first NQ reference string, **not** a generated provider
answer. The answer-aware policy uses the unchanged artifact and pinned
`cross-encoder/nli-deberta-v3-xsmall` revision
`a150876415327c80daeff35ca6f68f5ed8cf5c24`.

## Measured outcomes

All four systems saw the same 60 candidate pairs. Coverage is accepted candidates
divided by 60; it is **not** correct-answer coverage.

| System | ACCEPT | VERIFY | REJECT | Coverage | Warm decision p50 / p95 | Warm local lookup p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|
| Exact | 10 | 0 | 50 | 16.7% | 0.0013 / 0.0019 ms | 0.0013 / 0.0019 ms |
| Static 0.72 | 10 | 0 | 50 | 16.7% | 0.0055 / 0.0071 ms | 10.15 / 12.25 ms |
| Adaptive Tier 1 | 10 | 0 | 50 | 16.7% | 0.0231 / 0.0999 ms | 10.20 / 12.27 ms |
| Answer-aware v1 | 5 | 0 | 55 | 8.3% | 0.0069 / 51.68 ms | 10.72 / 62.19 ms |

Warm local lookup includes query embedding, nearest-neighbor retrieval, and
policy decision for semantic systems. Exact lookup times here are an in-memory
string comparison. These figures **exclude Redis, HTTP, provider calls, and
model load**; they are not live gateway end-to-end latency. Timing came from one
Windows 11 AMD64 / Python 3.13.2 run with `sentence-transformers` 6.1.0.

Among 50 distinct incoming questions, 41 were rejected by the answer policy's
existing `min_similarity=0.35` guard, six by the NLI contradiction/irrelevance
rule, two by negation mismatch, and one by number mismatch. The random 60-item
stored set rarely retrieves a close neighbor, so this pilot does not test
answer-aware acceptance on a representative set of hard near matches.

Five of the ten exact repeats were rejected by answer-aware v1 as
`invalid_candidate`: their float32 dot products were just above 1.0
(`1.000000119` or `1.000000238`). The frozen policy checks `similarity <= 1`
without a rounding tolerance. This is an implementation issue to fix in a
separate, versioned run; the pilot result was not retuned or overwritten.

No incorrect-acceptance rate is reported. NQ reference strings and unreviewed
cross-question matches do not establish that a specific cached answer is valid
for a new question. This sample is not production traffic, and its mix of exact
repeats and random distinct queries is a chosen pilot design, not traffic prevalence.
