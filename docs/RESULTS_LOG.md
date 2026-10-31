# Results and evidence index

Current result interpretation is in [experimental results](RESULTS_EXPERIMENTAL.md)
and [phase status](PHASE_STATUS.md). Source CSVs are under
[`evaluation/results/`](../evaluation/results/). Do not combine results from different
label rules or report an old development-fixture figure as a production error rate.

| Evidence | Source | Scope |
|---|---|---|
| Smoke candidate pairs | [`metrics.csv`](../evaluation/results/metrics.csv) | Hand-authored development fixture; the current policy version matters. |
| NQ historical oracle proxy | [`gold_verifier_policies.csv`](../evaluation/results/gold_verifier_policies.csv) | Five overlapping splits, strict and lenient reference-set labels; not reviewed actual answers. |
| Specific-answer audit | [`answer_label_audit.json`](../evaluation/results/answer_label_audit.json) | Counts where concrete cached text is absent from incoming references; adjudication pending. |
| Risk selection | [`gold_risk.csv`](../evaluation/results/gold_risk.csv) | Reject-all at 1%, 2%, 5% on correlated proxy data; no deployed guarantee. |
| Replay | [`gold_stream.csv`](../evaluation/results/gold_stream.csv) | Historical symmetric-alias replay; answer text was not represented. |
| Current directional replay | [validated bundle report](RESULTS_DIRECTIONAL.md) | Concrete reference-string simulation with lexical hash vectors; still no generated-answer truth. |
| Opt-in answer-aware policy | [controlled run report](RESULTS_ANSWER_AWARE.md) | 60 authored binary cases plus 2 ambiguous cases, warm local decision latency; no production guarantee. |
| Tests | [`checks.json`](../evaluation/results/checks.json) | Generated counts for its associated test run only. |

The chronological build history and its original figures are preserved in the
[historical results log](archive/RESULTS_LOG_HISTORICAL.md). Those measurements used
different code, hardware and datasets and should be cited only with their local scope.
