# Eleven valid live-path misses: development diagnosis

This inspection uses the saved `results_complete/` HTTP rows from commit
`3438a38`. It is development evidence. The frozen workload and historical
results are unchanged. All 11 suitable candidates were in the RedisSearch
shortlist above the 0.35 floor. In both OFF and ON variants, each suitable
candidate passed the enabled structural checks, received an NLI score, and
was individually **not accepted**. The applicability check deferred to NLI
for every suitable candidate; it did not cause these 11 misses. Scores below
0.2 produced REJECT; scores from 0.2 to below 0.9 produced VERIFY.

The ON trace has the same suitable-candidate rank, similarity, action, and NLI
score. Final notes below are the *saved* HTTP notes from the earlier gateway
version. Other candidates' decisions remain in each row's `candidate_trace`.

| Incoming task (family) | Suitable rank / similarity | Suitable action, NLI status / score | Saved final note OFF | Saved final note ON |
|---|---:|---|---|---|
| GitLab deploy staging, `What is the way...` | 1 / .9891 | VERIFY, scored / .887 | `answer_verify:uncertain_answer` | same |
| GitLab release to stage | 2 / .8230 | REJECT, scored / .016 | `answer_reject:answer_contradiction_or_irrelevance` | `answer_reject:applicability_environment_conflict` |
| PostgreSQL restore in stage, `What is the process...` | 2 / .8272 | VERIFY, scored / .499 | `answer_reject:answer_contradiction_or_irrelevance` | `answer_reject:applicability_environment_conflict` |
| PostgreSQL backup staging safely | 1 / .9422 | REJECT, scored / .004 | `answer_reject:answer_contradiction_or_irrelevance` | same |
| Kafka create invoices, `What is the way...` | 1 / .9928 | VERIFY, scored / .734 | `answer_verify:uncertain_answer` | same |
| Kafka delete invoices safely | 1 / .9661 | REJECT, scored / .005 | `answer_reject:answer_contradiction_or_irrelevance` | same |
| Argo deploy to amber, `What steps...` | 1 / .9724 | VERIFY, scored / .489 | `answer_verify:uncertain_answer` | same |
| Argo release to amber | 1 / .9357 | REJECT, scored / .017 | `answer_reject:answer_contradiction_or_irrelevance` | same |
| Argo preview in amber safely | 1 / .9597 | REJECT, scored / .004 | `answer_reject:answer_contradiction_or_irrelevance` | same |
| Docker scan, environment omitted | 1 / .8676 | VERIFY, scored / .891 | `answer_verify:uncertain_answer` | same |
| Docker release to staging | 1 / .8959 | REJECT, scored / .029 | `answer_reject:answer_contradiction_or_irrelevance` | same |

**Rank-two opportunities.** For GitLab release, rank one and rank two were
both individually rejected by NLI. For PostgreSQL restore, rank one was
rejected, while suitable rank two was uncertain at .499. Neither suitable
candidate was accepted and then discarded. The saved PostgreSQL final note
reported rank one's rejection despite the later uncertainty. This is a
reporting defect, fixed in the shared selector with a focused regression:
where rank one rejects and a later candidate is VERIFY, the final note now
reports the abstention; the candidate trace still shows both decisions.

Across all 11, **5 suitable candidates were VERIFY and 6 were REJECT** by
NLI. No candidate mutation/expiry, verification limit, timeout, or
cross-answer conflict blocked any of these valid requests. The selector's
conservative conflict, budget, and final identity rules remain intact. The
main reuse limitation here is the pinned NLI decision on the particular
answer assertion, not retrieval or top-k selection. Some low scores on
near-paraphrases show that this assertion formulation/model is not a reliable
technical applicability judge. The `.891` Docker case is near the frozen
`.9` acceptance threshold, but changing that threshold on inspected cases
would be test-set tuning.

## One bounded verifier alternative to evaluate later

Fine-tune **the already pinned DeBERTa-v3-xsmall cross-encoder** to classify
the concrete `(cached question, cached answer, incoming question)` as
reusable or abstain. Use independently established, grouped technical labels,
including changed actions, targets, permissions, versions, ambiguous
requirements, code, and long answers. Do not train on these inspected cases
and then report them as validation. Freeze a new family-disjoint HTTP/top-k
set before comparing against the current policy, with at least 150 valid,
150 invalid, and 100 ambiguous probes and competing candidates.

Acceptance criteria, all required: improve valid reuse by at least 10
percentage points **without increasing** incorrect accepts or ambiguous
approvals on that frozen set; retain conflict and timeout abstentions; report
95% binomial confidence intervals and all raw denominators. Measure cold
load, warm per-candidate verification and full HTTP p50/p95 over at least
three order-balanced runs on the same runner. Require warm verifier p95 no
more than twice the current model and process RSS no more than 1.2 GiB.
Training and evaluation must run offline with the existing pinned base weights;
**no new base-model download** is required or authorized. Publish the exact
fine-tuned artifact hash and its bytes before any enablement. If those
conditions fail, retain the current default and treat the alternative as a
negative experiment. This is a proposal, not an implemented or validated
quality improvement.
