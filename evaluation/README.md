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
The pair-level pipeline evaluates **given query pairs**, with density set to zero.
The separate `python -m evaluation.stream` replay fills a cache, measures real
neighbourhood density, and reports retrieval opportunities and unknown cross-pair
outcomes. `python -m evaluation.train_accept` trains proxy models and transfer
baselines; `python -m evaluation.risk_guarantee` exercises the bound on synthetic
IID data and a public pair-proxy shift. See the
[generated experimental results](../docs/RESULTS_EXPERIMENTAL.md). None of the
public source labels establishes that a particular cached answer is reusable. See
[`docs/DATASHEET.md`](../docs/DATASHEET.md) and
[`docs/PHASE_STATUS.md`](../docs/PHASE_STATUS.md) for the remaining work.

## NQ-Open oracle-answer study

With the pinned local MiniLM and NLI models available, run:

```powershell
python -m scripts.build_answer_pairs --download
python -m evaluation.gold_model
python scripts/summarize_experiments.py
```

The source, mined pairs, NLI feature cache, and any per-row judge opinions
stay in gitignored `data/`. Aggregate CSVs under `evaluation/results/` and
`docs/RESULTS_EXPERIMENTAL.md` are generated from that run. The gold label is
normalized NQ answer-alias agreement, not a human judgment of a generated
answer. PAWS transfer is reported separately with `query_pair_proxy` labels.
The judge validates against NQ gold first, then can judge only unlabelled
triples with actual cached answers; blank review rows are skipped. No paid
provider calls are involved. The reported judge failed validation, so its
opinions should not be used as correctness evidence.

The expanded miner records negative categories in `gold_mining.csv`, and the
model experiment records grouped partition sizes in `gold_split_sizes.csv`.
It also exports `false_accepts.csv`: a deterministic sample of 100 distinct
held-out gold-answer-mismatch accepts per static, adaptive and local-NLI learned
policy. The file contains both questions, both gold answer sets, negative type,
score, threshold and a heuristic answer-granularity flag. It is an error sample,
not a prevalence estimate; alias mismatches may include genuinely equivalent
answers written differently.
The old small-corpus risk, replay, and judge results remain labelled as
historical in the report. `python -m evaluation.gold_model --risk` regenerates
the expanded-corpus risk and false-accept files; the judge rerun and volatility
study remain separate future steps.

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
