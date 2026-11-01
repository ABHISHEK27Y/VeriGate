# Technical answer-reuse diagnosis and frozen comparison

The checkout began at `4e3c6fbfef8cbe48ce5743c37893e46026b1fedf` on
`codex/evaluation-integrity`; unrelated `audit/` remained untouched. This is a
controlled, fixed-candidate experiment with real pinned MiniLM embeddings and
the pinned local NLI model. It is not a live top-k HTTP or provider evaluation.
The 30 cases and their independent stipulated labels were committed in
`dfd70a5d3a976106a4f87c2f77abea9e2f4d9251` **before** either variant ran.

## Development failures inspected

The prior 10-family comparison's current policy accepted one labelled invalid
and four labelled ambiguous rows. Each selected candidate was the stipulated
stored row, with MiniLM similarity above 0.35. The default technical identity
guard was off; the enabled number, negation, named-work, answer-mention,
scope-word, and answer-type checks did not stop these rows. No NLI input was
truncated. The stored answers are complete for their **narrow stored tasks**;
their specificity is exactly what makes reuse unsafe or unresolved elsewhere.

| Development request against stored answer | Similarity | Forward NLI | Decision issue |
|---|---:|---:|---|
| Apply Terraform change vs answer to plan Terraform change | .933 | .928 | Wrong action accepted. |
| Roll back deployment without product/environment vs Kubernetes staging answer | .699 | .966 | Missing scope accepted. |
| Change Terraform workspace vs answer to plan a change | .889 | .979 | Operation underspecified. |
| Run Pytest test without marker vs answer for slow marker | .821 | .954 | Missing marker accepted. |
| Send request without HTTP method vs answer for PUT | .774 | .963 | Missing method accepted. |

For every row the model received `The answer to <stored question> is <cached
answer>.` as premise and the corresponding incoming-question assertion as
hypothesis. Repeating the same answer on both sides can make a specific answer
look plausible for a broader request. A reverse assertion check was therefore
tested as an experimental information-loss detector. On these inspected
development cases it downgraded the Terraform action error and two missing-
scope approvals, but still accepted the Terraform-workspace and Pytest-marker
ambiguities. Those examples were not used as fresh test evidence.

## Disjoint frozen result

The [workload](workload.json) has 10 new technical families with one valid,
one invalid, and one explicitly underspecified request each. Labels derive from
the frozen per-row task contracts, not from model outputs. The single stored
candidate and real MiniLM similarity were identical for both variants. All
10 valid candidates cleared the retrieval floor; all misses happened later.

| Variant | Valid reuse | Invalid accepts | Ambiguous accepts | VERIFY / all | Verifier calls | Verifier median / p95 |
|---|---:|---:|---:|---:|---:|---:|
| Current answer assertion | 4/10 | 0/10 | 3/10 | 14/30 | 16 | 84.600 / 101.843 ms |
| Bidirectional answer assertion | 3/10 | 0/10 | 3/10 | 15/30 | 23 | 94.781 / 185.194 ms |

The experimental check lost a valid Helm paraphrase (reverse score .809) and
removed none of the three remaining ambiguous accepts (SQLite journal mode,
GraphQL order operation, Celery task handling). It did not improve the measured
trade-off. The existing answer-aware policy remains unchanged, and exact
matching remains the deployment default; the reverse check exists only in the
evaluation script. Two separate runs gave identical 60 row actions; the
second added verifier-call timing. The primary artifacts are
`results_timed/decisions.csv` and `results_timed/summary.json`.

The deliberately long answer produced a 596-token paired input against the
512-token model window and a conservative `context_too_long` VERIFY. Other
valid misses included structural `scope_changed` and `number_mismatch` outcomes
and NLI uncertainty. These are separate recall limitations, not evidence that
the reverse check repairs them. No new threshold was selected on this lockbox.

On this Windows CPU process, RSS was 54.0 MB initially, 571.4 MB after MiniLM
encoding, 797.7 MB after NLI prewarm, and 814.9 MB after both variants. Both
variants share one model; this run does not isolate a per-variant memory delta.
Decision p95 across all 30 rows was 99.177 ms current and 176.355 ms reverse;
many rows exit before NLI, so the verifier-call figures above are the more
relevant model-path timing. These are local timings, not HTTP latency.

The controlled labels are independent of the verifier but are authored
stipulations, not human-reviewed production traffic. The sample is small and
does not establish real-world error rates or universal technical understanding.
Automatic workspace selection, isolation, completion checks, deadlines, and
candidate traces were not changed. Cache-clear fencing, cross-worker memo
purge, full HTTP replay, and real-provider validation remain pending.
