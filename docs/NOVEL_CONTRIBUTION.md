# Novel Contribution — Deep Dive

## The Adaptive, Self-Verifying Semantic Cache

This is the heart of the major project — the part that is genuinely *yours* and that you
defend in front of examiners. This document explains the three sub-contributions precisely
enough to implement and to write up as a methodology chapter.

---

## 0. Background: how a naive semantic cache works (the baseline)

1. Keep a store of past `(query, embedding, answer)` entries.
2. For a new query `q`: compute embedding `e(q)`; find the nearest stored entry `p` by
   cosine similarity.
3. If `sim(e(q), e(p)) >= T` for a **fixed** threshold `T` (e.g. 0.95) → return `p.answer`.
4. Else → call the LLM, then store `(q, e(q), answer)`.

**The flaw:** one global `T` cannot fit all queries.
- Fact-dense short queries ("capital of Austria?") are embedding-close to different-answer
  queries ("capital of Australia?") → with a normal `T` you get a **false hit** (wrong
  answer served silently).
- Long open-ended queries that *should* share an answer often fall *below* `T` → a **missed
  hit** (wasted money).
- Time-sensitive queries ("stock price now?") get cached and go **stale**.

VeriGate addresses all three.

---

## 1. Sub-contribution A — Adaptive per-query thresholding

**Idea:** compute the threshold `T(q)` as a function of the query, not a constant.

**Signals that should make matching STRICTER (higher `T`):**
- **Named entities / proper nouns** (countries, names, products) — small textual changes
  flip the correct answer.
- **Numbers, dates, quantities** — "5 GB plan" vs "50 GB plan".
- **Short queries** — fewer tokens ⇒ each token matters more.
- **High neighbourhood density** — many near-but-distinct stored queries around `q` ⇒ higher
  collision risk ⇒ be careful.

**Signals that allow LOOSER matching (lower `T`):**
- **Long, descriptive, open-ended** queries where phrasing varies but intent is stable.
- **Low entity/number content.**

**Concrete formulation (implementable):**

```
T(q) = clip( T_base
             + w1 * entity_density(q)
             + w2 * number_flag(q)
             + w3 * shortness(q)
             + w4 * neighbourhood_density(q) ,
             T_min, T_max )
```

where:
- `entity_density(q)` = (#named entities) / (#tokens), from a fast NER (e.g. spaCy).
- `number_flag(q)` = 1 if the query contains numbers/dates/quantities, else 0.
- `shortness(q)` = a decreasing function of token count (short ⇒ larger value).
- `neighbourhood_density(q)` = how many stored entries lie within a margin of the nearest
  one (many ⇒ larger value).
- `w1..w4` are weights; `T_base`, `T_min`, `T_max` bound the range.

**How to set the weights (this is a real experiment for the report):** treat `w1..w4` and
`T_base` as hyper-parameters and tune them on a validation split of the benchmark to
maximize a correctness-aware objective (see §4). Report the chosen values and a sensitivity
analysis. *(Optional stretch: learn `T(q)` directly with a small logistic-regression
classifier over these features — trained to predict "is this pair truly equivalent?" — and
use its probability as the accept score. This turns the heuristic into a learned model,
which strengthens the novelty.)*

---

## 2. Sub-contribution B — Self-verification (reject false hits)

Even with an adaptive threshold, a candidate hit can still be wrong. Before serving a
cached answer, **verify** that the new query `q` and the stored query `p.query` are truly
equivalent — a cheap second opinion that does **not** call the expensive LLM.

**Two-tier verifier (cheap → less cheap; stop as soon as confident):**

**Tier 1 — symbolic/lexical checks (microseconds):**
- **Entity-set match:** the set of named entities in `q` must equal that in `p.query`.
  ("Austria" ≠ "Australia" ⇒ reject.)
- **Number/date match:** numeric values and units must match. ("5 GB" ≠ "50 GB" ⇒ reject.)
- **Negation/polarity check:** presence of negation flips meaning ("is X safe?" vs "is X
  *not* safe?").

If Tier 1 finds a mismatch → **reject** (treat as miss). If Tier 1 is clean but the
similarity is only borderline → escalate to Tier 2.

**Tier 2 — lightweight semantic equivalence (milliseconds):** *(IMPLEMENTED — Phase 4b)*
- A small **Natural Language Inference (NLI)** cross-encoder
  (`cross-encoder/nli-deberta-v3-xsmall`) checks **bidirectional entailment** between `q`
  and `p.query`. Both directions must entail ⇒ equivalent. This catches related-topic
  negatives that Tier-1's structural checks miss (e.g. *reset password* vs *reset router*).
- **Measured finding (see RESULTS_LOG Phase 4b):** Tier-2 drives false-hit rate to 0 at any
  threshold, but is conservative (lowers recall) and is largely redundant once the adaptive
  threshold is active. It is therefore **opt-in** (`VERIFIER_NLI`), a "max-correctness mode"
  rather than the default. Future work: run Tier-2 only on *borderline* similarities, and
  tune `nli_threshold` to trade recall vs. correctness.

**Design rule:** Tier 2 only runs when needed (borderline cases), keeping average overhead
low. The verifier is **conservative**: when in doubt, reject (miss) — a miss costs money,
a false hit costs correctness, and we optimize for correctness.

---

## 3. Sub-contribution C — Staleness / volatility detection

Some queries must **never** be cached because their answers change over time.

**Detector (rule + optional classifier):**
- **Temporal keywords:** "today", "now", "current", "latest", "this week", "live", "price",
  "weather", "score", stock tickers, etc.
- **Real-time intent patterns:** questions asking for present state.
- **Optional:** a small text classifier trained on a labelled set of volatile vs. stable
  queries for better recall than keywords alone.
- **TTL fallback:** even cacheable entries carry a **time-to-live**; borderline-volatility
  entries get short TTLs so any staleness self-heals.

If flagged volatile → bypass the cache (always call the LLM), and do not store the result
(or store with a very short TTL).

---

## 4. Why this is a defensible contribution

- It targets a **specific, documented weakness** (false hits from static thresholds) that
  existing systems (GPTCache et al.) do not address well.
- Each sub-contribution is **implementable, measurable, and ablatable** (you can turn each
  on/off and show its individual effect — examiners love ablation studies).
- The result is a **trade-off improvement with numbers**, not a subjective claim.

**Objective to optimize / report (correctness-aware):**
Rather than maximizing hit-rate alone, VeriGate maximizes a correctness-aware score, e.g.
maximize hit-rate **subject to** false-hit-rate ≤ ε, or maximize
`(true_hits − penalty × false_hits)`. This framing is the intellectual core of the write-up.

---

## 5. Ablation plan (what you'll show)

| Variant | Adaptive T | Verifier | Staleness | Purpose |
|---|:---:|:---:|:---:|---|
| Baseline (static) | ✗ | ✗ | ✗ | The thing everyone builds. |
| + Adaptive T | ✓ | ✗ | ✗ | Effect of adaptive thresholding alone. |
| + Verifier | ✗ | ✓ | ✗ | Effect of verification alone. |
| + Staleness | ✗ | ✗ | ✓ | Effect of staleness handling alone. |
| **VeriGate (full)** | ✓ | ✓ | ✓ | The complete system. |

Reporting each row's hit-rate, false-hit-rate, cost saved, and added latency turns the
methodology into a clean experimental story.

---

## 6. Pseudocode (end-to-end cache decision)

```python
def semantic_cache_lookup(q):
    if is_volatile(q):                     # Sub-contribution C
        return MISS  # never cache volatile queries

    e = embed(q)
    p, sim = nearest_neighbor(e)           # Redis vector KNN
    if p is None:
        return MISS

    T = adaptive_threshold(q, neighborhood(e))   # Sub-contribution A
    if sim < T:
        return MISS

    if not verify_equivalent(q, p.query):  # Sub-contribution B (2-tier)
        record("false_hit_rejected")
        return MISS

    record("cache_hit")
    return HIT(p.answer)
```

Everything below the volatility check is the fast, correctness-guarded hot path. This
single function *is* your contribution — everything else in the project exists to host,
scale, and measure it.
