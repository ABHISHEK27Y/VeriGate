# Evaluation: current smoke fixture

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
