# NQ-Open close-neighbor diagnostic

This second [NQ-Open original dev](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open)
workload is a **diagnostic proxy**, not a final answer-quality test. The source
is [CC BY-SA 3.0](https://github.com/google-research-datasets/natural-questions/blob/master/nq_open/README.md).
The [selection freeze](../evaluation/close_neighbor_freeze_v1.json) records the
source hash, pinned model and artifact, minimum similarity, and sample sizes.
The [manifest](../evaluation/runs/nq_dev_close_neighbors_v2/manifest.json),
[decisions](../evaluation/runs/nq_dev_close_neighbors_v2/decisions.csv), and
[metrics](../evaluation/runs/nq_dev_close_neighbors_v2/metrics.csv) preserve the
run. Reproduce with `EMBEDDING_BACKEND=minilm python -m scripts.run_close_neighbor_pilot <new_run_id>`
after obtaining the gitignored NQ dev source and mined NQ train pairs described
in the freeze and earlier evaluation instructions.

The runner excludes the authored development and held-out examples, mined NQ
train pairs, and random NQ dev pilot queries. It embeds eligible questions with
pinned MiniLM, selects distinct pairs with cosine similarity at least **0.7**,
and avoids reusing a question across the 40 selected pairs. The first NQ
reference answer is the concrete cached answer. A positive proxy means that
answer appears in the incoming question's normalized NQ reference strings;
lenient answer overlaps are excluded from the negative pool as uncertain.
Twenty proxy positives and twenty proxy negatives were deliberately selected.
This balance is not traffic prevalence, and related source documents are not
available for a final family-level split. All rows are labelled diagnostic.

| Policy | ACCEPT / 40 | VERIFY | REJECT | Accepted reference matches / 20 | Accepted reference mismatches / 20 | Warm decision p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|
| Exact | 0 | 0 | 40 | 0 | 0 | 0.002 / 0.002 ms |
| Static 0.72 | 34 | 0 | 6 | 16 | 18 | 0.005 / 0.008 ms |
| Adaptive Tier 1 | 1 | 0 | 39 | 1 | 0 | 0.042 / 0.123 ms |
| Answer-aware v1 | 8 | 5 | 27 | 6 | 2 | 44.68 / 49.93 ms |

The answer-aware policy accepted two **reference-mismatch** pairs. One asks who
Betty ends up with after a cached question asks whether Archie ends up with
Betty or Veronica; the cached answer was `Betty`. The other changes “the last
year the Eagles went to the Superbowl” into “when did the Eagles play in the
Superbowl”; the cached answer was `following the 2017 season`. These are
substantive direction/scope concerns, but the reference proxy alone cannot
adjudicate all readings or prove the exact number of wrong answers. The runner
made no provider calls. Warm decision latency excludes embeddings, retrieval,
Redis, HTTP, and provider generation.

This run does not justify relaxing policy thresholds to gain hits. A separate
independent source with reviewed specific-answer labels is required before
claiming a useful safe operating point.

## Follow-up: policy runtime v3 (30 October 2026)

The [new run](../evaluation/runs/nq_dev_close_neighbors_v4/manifest.json) uses the
same frozen 40 pairs and unchanged policy artifact. It adds general abstentions
when the proposed answer appears in the incoming question, and when a question
adds or drops an ordinal/superlative scope. The old v2 run above is preserved.

The Betty pair is a confirmed direction error under the recorded references:
the cached answer to whom **Archie** ends up with was `Betty`, while the incoming
question asks whom **Betty** ends up with and lists `Archie Andrews` as its NQ
reference. The new policy returns VERIFY. For the Eagles, NQ lists `February 6,
2005` for an unscoped “when did they play” question, while the cached answer is
“following the 2017 season” for the **last** appearance. The latter might also
be a valid occurrence; the reference alone cannot decide. The new policy returns
VERIFY because scope changed.

| Answer-aware runtime | ACCEPT / 40 | VERIFY | REJECT | Accepted reference matches | Accepted reference mismatches |
|---|---:|---:|---:|---:|---:|
| v2 historical | 8 | 5 | 27 | 6 | 2 |
| v3 follow-up | 6 | 10 | 24 | 6 | 0 |

The six accepted reference matches are **proxy matches**, not independently
reviewed correctness. The selection was deliberately balanced 20/20, so zero
accepted mismatches here is neither a traffic error rate nor a safety guarantee.
