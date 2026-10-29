# Evaluation: pair-level evidence and its limits

The newer pipeline loads QQP, PAWS-Wiki labeled-final, and STS-B into gitignored
`data/`, then makes query-group-separated train/validation/calibration/test splits.
`make reproduce` runs five fixed seeds, tunes the static baseline on validation
only, writes per-split metrics and grouped-bootstrap intervals to
`evaluation/results/v2_pair_metrics.csv`, and generates
[`docs/RESULTS_V2.md`](../docs/RESULTS_V2.md). First run:

```powershell
python scripts/download_evaluation_data.py qqp stsb paws
make reproduce
```

`make reproduce-fast` uses only the historical smoke fixture and overwrites the
same generated outputs; do not confuse that output with the public-source run.
The new pipeline still evaluates **given query pairs**, with density set to zero.
It does not evaluate candidate retrieval or a filling cache, and none of the
source labels establishes that a particular cached answer is reusable. See
[`docs/DATASHEET.md`](../docs/DATASHEET.md) and
[`docs/PHASE_STATUS.md`](../docs/PHASE_STATUS.md) for the remaining work.

## Historical smoke evaluator

From the repository root, using the locked development environment:

```powershell
python -m evaluation.run
python scripts/export_report_tables.py
```

The first command uses real MiniLM embeddings and writes `evaluation/results/metrics.csv`,
`tradeoff.png`, and `ablation.png`. It does **not** call a paid provider. Optional local
question-to-question NLI is excluded by default; run `python -m evaluation.run --with-nli`
only when the pinned model is available. If model loading fails, the result is marked
`unavailable` and must not be interpreted as NLI quality.

`benchmark.py` contains a small, hand-authored **query-pair** fixture. Its labels express
intended paraphrase equivalence, not whether a particular cached answer would answer the
new request. The same fixture influenced the heuristic threshold. There is no independent
annotation, train/validation/test split, candidate retrieval measurement, or replay with
a changing cache. The evaluator passes neighbourhood density zero, unlike live semantic
retrieval. Do not present these outputs as final thesis evidence.

The CSV deliberately uses explicit denominators:

| Field | Definition |
|---|---|
| `positive_recall` | Accepted positive pairs / all positive pairs |
| `negative_false_accept_rate` | Accepted negative pairs / all negative pairs |
| `acceptance_rate` | All accepted pairs / all labelled pairs |
| `false_reuse_fraction` | Accepted negative pairs / all accepted pairs; undefined when none accepted |
| `precision` | Accepted positive pairs / all accepted pairs; undefined when none accepted |

Neither `positive_recall` nor `acceptance_rate` is a real workload hit rate or cost saving.
The labels are query-only, so even `false_reuse_fraction` is only a fixture proxy for
incorrect answer reuse. The next phase must build answer-aware labels and group-separated
splits before tuning a policy. See [the research baseline](../docs/RESEARCH_BASELINE.md).

The other scripts (`latency.py`, `backend_compare.py`, `cascade.py`) produce separate
engineering measurements or illustrative cost models. Their CSVs must be read with their
own assumptions; cascade hard-label recall is **not** judged provider-answer quality.
