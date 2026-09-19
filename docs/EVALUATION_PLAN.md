# Evaluation Plan

How VeriGate proves its novel contribution with numbers. This maps directly to the
"Results & Evaluation" chapter of the report — the section examiners weigh most heavily.

---

## 1. What we are measuring (research questions)

- **RQ1:** Does adaptive + verified caching reduce **false cache hits** compared to a
  static-threshold baseline, at a comparable hit-rate?
- **RQ2:** What is the **latency overhead** of verification on the cache-hit path?
- **RQ3:** How much **cost/latency** does the cache save overall versus no cache?
- **RQ4:** What does each component contribute (ablation)?

---

## 2. The benchmark dataset

We need query pairs with ground-truth labels of **equivalent** vs **not equivalent**.

**Positive pairs (should share an answer):** paraphrases of the same question.
Sources: paraphrase datasets (e.g. Quora Question Pairs "duplicate" pairs), plus
LLM-generated paraphrases (hand-verified sample).

**Hard negative pairs (embedding-close but different answer):** the crucial, novel part.
Construct by:
- Swapping one entity/number ("Austria"→"Australia", "5 GB"→"50 GB").
- Minimal edits that flip meaning (add negation, change a date).
- Mining "not duplicate but similar" pairs from Quora Question Pairs.

**Volatile queries:** a labelled set of time-sensitive vs. stable questions for the
staleness detector.

**Splits:** train/validation (for tuning weights/threshold) and a held-out **test** set for
final reported numbers. Document dataset size and construction so it's reproducible.

> Deliverable: `benchmark/` with the dataset + generation scripts + a short datasheet
> (how many pairs, sources, how labels were verified).

---

## 3. Metrics

**Correctness of caching (primary):**
- **Hit-rate** = cache hits / cacheable queries. (savings proxy)
- **False-hit rate** = wrong-answer hits / total hits. **(the metric we improve)**
- **Precision of hits** = true hits / all hits.
- Treat cache acceptance as a classifier over "equivalent?" and report **precision,
  recall, F1**, plus a **precision–recall / ROC curve** as the threshold varies.

**Performance:**
- **Latency:** p50/p95/p99 for (a) cache-hit path, (b) cache-miss/LLM path, (c) verifier
  overhead specifically.
- **Cost saved:** estimated $ saved = (hits × avg cost per LLM call).
- **Throughput:** sustained req/s at which SLOs hold (from load test).

**System:**
- Rate-limiter correctness under concurrency.
- Failover success rate and time-to-failover when a provider is killed.

---

## 4. Baselines to compare against

1. **No cache** (upper bound on cost/latency).
2. **Static-threshold semantic cache** at several fixed `T` values (0.90, 0.93, 0.95,
   0.97) — this is the "existing systems" baseline; sweeping `T` shows the trade-off curve
   VeriGate improves on.
3. **Exact-match cache** (string equality) — the trivial baseline.
4. **VeriGate** (full) and its ablations (see NOVEL_CONTRIBUTION §5).

**The money graph:** plot **false-hit-rate (x) vs hit-rate (y)**. The static baseline traces
one curve as `T` varies; VeriGate should sit **above/left** of it (more hits at fewer false
hits). This single figure is the visual proof of the contribution.

---

## 5. Experimental procedure

1. Warm the cache by replaying a stream of queries (with realistic repeats/paraphrases).
2. Run the labelled test pairs through each variant; record hit/miss + correctness using
   ground-truth labels.
3. Record latency percentiles per path.
4. Sweep the baseline threshold to trace its trade-off curve.
5. Run ablations (toggle adaptive-T, verifier, staleness).
6. Load-test with a mock provider (k6/Locust) to get throughput + verify rate limiting and
   failover independently of real API costs/limits.

**Controls for fairness:** same embedding model, same dataset, same hardware, same vector
index for every variant. Only the decision logic changes.

---

## 6. Expected/target results (to validate, not assume)

- **≥50% reduction in false-hit rate** vs. the best comparable static threshold, at similar
  hit-rate. *(target — the actual number is what you report)*
- **Verifier overhead** small enough that the cache-hit path remains ~an order of magnitude
  faster than an LLM call.
- Clear ablation showing verification is the biggest single contributor to false-hit
  reduction, with adaptive-T improving the hit-rate/false-hit trade-off.

> A rigorous **negative or mixed** result is still a valid major-project outcome if analysed
> honestly — e.g. "adaptive-T gave marginal gains but verification was decisive." Examiners
> reward sound methodology over inflated claims.

---

## 7. Reproducibility checklist

- [ ] Dataset + generation scripts committed.
- [ ] Fixed random seeds; documented embedding model + version.
- [ ] One command to run each experiment and regenerate every figure.
- [ ] Hardware/software environment recorded.
- [ ] Raw results (CSV) + plotting notebook committed alongside the figures.
