# Evaluation data and provenance

The current public datasets label **pairs of texts**, not whether a particular cached
answer can answer the incoming request. The historical VeriGate smoke fixture has 30
hand-authored pairs and was used during heuristic development. It is useful for catching
regressions, **not** for an independent thesis result.

| Source | Input expected by `evaluation.datasets` | Pair-label interpretation | Rights and limits |
|---|---|---|---|
| QQP | `data/qqp.tsv`: `question1`, `question2`, `is_duplicate` | Quora duplicate flag | Quora's original terms need to be checked before redistribution or commercial use. The [GLUE FAQ](https://gluebenchmark.com/faq/) defers to source licences. No QQP text is committed here. Duplicate does not prove answer reuse. |
| PAWS | `data/paws.tsv`: `sentence1`, `sentence2`, `label` | Human-judged paraphrase label from PAWS-Wiki *labeled final* | [Google's source licence](https://github.com/google-research-datasets/paws/blob/master/LICENSE) permits use and requests attribution. High lexical overlap is an adversarial challenge; sentences are not necessarily questions. Do not mix in noisy unlabeled PAWS rows. |
| STS-B | `data/stsb.tsv`: `sentence1`, `sentence2`, `score` | Score ≥ 4.0 on the 0–5 scale is a **binarization proxy**, not a native equivalence label | [GLUE](https://gluebenchmark.com/faq/) defers to source rights; STS-B mixes text from multiple source corpora with different licences. The threshold is fixed before evaluation. No text is committed here. |
| VeriGate smoke | `evaluation/benchmark.py` | Author-intended equivalent / different | Hand-written, small, no independent annotation, and influenced policy design. |

All source text stays under gitignored `data/`. `evaluation.datasets.group_split` keeps
repeated normalized queries and declared families together across train, validation,
calibration, and test. This prevents exact-query leakage. It cannot infer unseen semantic
families or shared source documents; those must be declared when building answer-aware data.
Use seeds 11, 23, 37, 53, and 71 for repeated splits. The public data are not VeriGate
traffic, and their class balance is not deployment prevalence.

## Answer-aware annotation contract

Each record needs stored query, **actual cached answer**, incoming query, tenant/context
and version if relevant, source ID, provenance, annotation status, `answer_reusable`, and a
short reason. Reviewers should answer: *Would serving this exact answer, under the same
context and version, satisfy the incoming query without a materially wrong or missing
claim?* A valid paraphrase can still be non-reusable when the answer is incomplete, stale,
or tied to another context. Reject ambiguous cases or mark them `uncertain`; never force
them to a binary truth label.

Review cases in this order: identity and quantity substitutions, negation and relationship
reversals, added constraints, partial answers, freshness/version changes, then ordinary
paraphrases. Two independent reviewers should resolve disagreements before a row enters
the held-out answer-aware set. Track reviewer IDs and resolution status separately from
the model features. No independent human review has been completed in this repository.

The review queue should be a local TSV under `data/answer_review.tsv` with those fields.
Do not publish private prompts or answers. Public pair labels must remain
`source_pair_label`, with `answer_reusable` unset until a real answer is reviewed.
