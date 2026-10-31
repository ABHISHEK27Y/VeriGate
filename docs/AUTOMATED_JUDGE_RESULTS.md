# Automated answer judges: local diagnostic run

Source: [`automated_judge_validation.json`](../evaluation/results/automated_judge_validation.json).
Run command: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m scripts.evaluate_automated_judges`.
The script stores row-level decisions under gitignored `data/automated_answer_judges.tsv`.
Each row includes the specific cached answer, both model decisions, prompts,
versions, scores or explanations, and whether the judges agree. This run used
15 controlled cases with known labels and one ambiguous case excluded from
accuracy. Those cases include entities, dates, roles, tense, numbers and paraphrases.

| Judge | Correct / known | Precision for YES | Recall for YES | Finding |
|---|---:|---:|---:|---|
| FLAN-T5-small, pinned revision | 7 / 15 | undefined | 0 / 8 | Predicted no YES on the controlled set; unsuitable as an acceptance oracle. |
| NLI DeBERTa xsmall, pinned revision | 13 / 15 | 6 / 6 | 6 / 8 | Missed one valid same-author case and one number paraphrase. Small, authored controls cannot establish generalization. |

The 350-row queue stays `model_judged`: 200 diagnostic rows and 150 random rows.
The judges disagreed on 95 diagnostic and 73 random rows. These are *model
disagreements*, not observed answer errors. The controlled set was written for
this evaluation and is development data, so its scores are preliminary. The
random subset cannot supply a reliable error prevalence when the judges have
not been independently validated for that population. No row in this run is
human-reviewed. FLAN generated only a decision token; its saved explanation
field explicitly says that it supplied no free-text rationale.

The NLI prompt tests whether an assertion connecting the stored question and
answer entails the same assertion for the incoming question. This is an
answer-aware model opinion. It does not check the real-world truth of either
assertion. The model's high score on the ambiguous Georgia case shows why
ambiguity needs an abstention path rather than a blanket acceptance claim.
