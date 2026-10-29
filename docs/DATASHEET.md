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
| NQ-Open train | `data/NQ-open.train.jsonl` from the [official NQ-Open repository](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open) | Mined factoid pairs with `gold_answer_match`: normalized reference-answer alias sets intersect | [CC BY-SA 3.0](https://github.com/google-research-datasets/natural-questions/blob/master/nq_open/README.md). Raw questions and answers stay in gitignored `data/`; derived aggregate results may be committed. |

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

Run `python -m scripts.build_answer_review_queue` after downloading QQP and PAWS.
The command creates a balanced local queue and refuses to overwrite existing review
work. It leaves cached answers, reviewer IDs, answer labels, reasons, tenant IDs,
context versions, and answer versions blank. `reviewed_answers()` ignores unfinished
rows and rejects a purportedly resolved row without two distinct reviewers and
those required fields. A freshly generated queue is **entirely unreviewed**.

## NQ-Open gold-answer-match proxy

`python -m scripts.build_answer_pairs --download` fetches the official NQ-Open
train JSONL if needed, samples repeated-answer groups, embeds questions with the
pinned MiniLM model, and mines at least 10,000 high-similarity pairs. Negatives
are proposed by number substitution, a same-subject/different-relation template,
a lexical entity-slot substitution, or a lexical-plus-semantic fallback requiring
shared content words. All must have disjoint reference-answer aliases. The
first three categories are explicit hard-case proxies; the last is not selected
by MiniLM similarity alone. Type counts are in `evaluation/results/gold_mining.csv`.
It stores the source and derived SHA-256 hashes, model revision, seed, selection
parameters, and class counts in a local provenance JSON. Positive questions
appear in one pair; a negative question may appear in two. `group_split()`
keeps connected query components together for five-seed
train/validation/calibration/test evaluation. The expanded study reserves
25% for calibration; split counts are in `gold_split_sizes.csv`.

The label compares normalized gold answer **alias sets**, ignoring case,
punctuation, articles and repeated whitespace. The cached answer is an oracle
NQ reference string, **not** a generated provider answer. Matching aliases
can correspond to different senses or incomplete answers; nonmatching aliases
can still be equivalent (for example, unlisted synonyms or number formats).
NQ-Open is factoid English Wikipedia QA, so these labels do not cover
multi-part instructions, dialogue, retrieval context, time-sensitive answers,
or tenant-specific policy. The miner intentionally enriches repeated answers
and structural hard negatives; its roughly balanced classes are not deployment
prevalence. NQ-Open questions are lowercased, so capitalization-based named-
entity checks cannot identify entities here. The entity-slot type is a lexical
proxy; it can include non-entities. The different-attribute type is sparse and
cannot support a standalone performance conclusion. The gold-answer study must
be reported separately from QQP/PAWS
query-pair labels and from any model-judged labels. It supports a stronger
*factoid proxy* than query paraphrase, not a production answer-error claim.

TriviaQA was assessed but is not included in this pass. Its
[official release](https://nlp.cs.washington.edu/triviaqa/) bundles questions
with a large evidence corpus and a different answer schema; it needs a
separate loader, provenance, and source-separated evaluation. No TriviaQA
rows are counted in the NQ results.
