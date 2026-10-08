# Evaluation Harness

This produces the results that prove VeriGate's contribution. It compares the cache
policies on a labelled benchmark and generates the figures + CSV for the report.

## Run it

```bash
cd "D:\miniProject\7th sem\llm-gateway"
.\.venv\Scripts\Activate.ps1
python -m evaluation.run
```

Forces the real `minilm` embeddings. Outputs land in `evaluation/results/`:
- `metrics.csv` — the ablation table (raw numbers).
- `tradeoff.png` — **the money graph** (false-hit rate vs hit rate).
- `ablation.png` — per-component bar chart.

For the latency results (RQ2 + cache speedup):
```bash
python -m evaluation.latency
```
Outputs `latency.csv`, `latency.png` (per-stage bars), `latency_scaling.png` (KNN O(n) growth).

## Files
- `benchmark.py` — the labelled dataset: positive (equivalent) pairs, hard-negative pairs
  grouped by failure mode (entity swap / number swap / negation / related topic), plus
  volatile queries and stable controls.
- `run.py` — embeds every query once, evaluates each policy, sweeps the baseline threshold,
  writes the CSV, and renders the figures.

## How to read the results

**The money graph (`tradeoff.png`).** Two trade-off curves, each traced by sweeping the
similarity threshold:
- red = static-threshold baseline (what existing systems do),
- blue = same, but with the self-verifier enabled,
- green star = full VeriGate (adaptive threshold + verifier).

The blue curve sits **above and to the left** of the red one: at any given hit-rate it
serves far fewer wrong answers. That domination *is* the contribution.

**Ablation table (`metrics.csv` / console).** `hit-rate` = savings, `false-hit rate` =
wrong answers served (lower is better), `precision` = fraction of hits that were correct.
The by-type breakdown shows the **verifier** eliminates entity/number/negation false hits
and the **adaptive threshold** clears related-topic ones.

## Honest limitations (good to state in the report)
- The benchmark is a compact, hand-curated seed set. Absolute numbers (e.g. hit-rate) are
  dataset-dependent; the **relative** comparison (VeriGate vs baseline) is the result.
- "Related-topic" negatives with no structural difference (e.g. *reset password* vs *reset
  router*) can only be separated by the threshold, which trades off against paraphrase
  recall. This is the motivation for **Tier-2 (NLI) verification** — the main future work.

## To strengthen for the final report
- Expand the dataset (mine Quora Question Pairs; generate + hand-verify paraphrases).
- Tune the adaptive-threshold weights on a validation split (report a sensitivity analysis).
- Add the Tier-2 NLI verifier and re-run the ablation.
- Add latency measurements (verifier overhead on the hit path).
