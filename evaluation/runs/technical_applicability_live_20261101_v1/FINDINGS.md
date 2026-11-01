# Live semantic applicability challenge

The 25-probe, five-family workload and independent stipulated suitability
labels were frozen in commit `9e673e42dc59c29d9305bab22c5e389632d79c7e`
before evaluation. Each probe began with the same three seeded answers in an
isolated Redis Stack tenant. The two variants used the same request order,
MiniLM `all-MiniLM-L6-v2` revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, pinned NLI
`cross-encoder/nli-deberta-v3-xsmall` revision
`a150876415327c80daeff35ca6f68f5ed8cf5c24`, answer-policy artifact
(`accept_at=.9`, `reject_below=.2`, `min_similarity=.35`), retrieval/verification
limit 5, and verification budget 1500 ms. Only
`ANSWER_POLICY_APPLICABILITY_GUARD` changed. The actual development gateway
handled HTTP requests through MiniLM, RedisSearch top-k, answer-aware NLI, and
a controlled fixed-answer provider. No paid calls were made. The provider
answer map was not available to retrieval or verification.

| Live HTTP result | Guard OFF | Guard ON |
|---|---:|---:|
| Valid answers reused | 4/15 | 4/15 |
| Incorrect accepts, invalid probes | 0/5 | 0/5 |
| Ambiguous approvals | 0/5 | 0/5 |
| Valid retrieval failures | 0/15 | 0/15 |
| Request-level verification abstentions / all probes | 10/25 | 10/25 |
| Misses after candidate assessment | 21/25 | 21/25 |
| Controlled-provider calls | 21 | 21 |
| Candidate NLI scores observed in traces | 74 | 25 |
| Candidate applicability decisions in traces | 0 | 50 |
| Cold process startup through readiness | 39.383 s | 36.280 s |
| First HTTP response after readiness | 275.495 ms | 134.904 ms |
| Subsequent HTTP median / p95 | 341.792 / 1458.667 ms | 155.311 / 279.052 ms |

All 15 suitable candidates appeared in RedisSearch's five-result shortlist;
some ranked second. None of the second-ranked suitable candidates was selected
on this workload. The 11 valid misses were verifier/selection misses, not
retrieval absence. Ranked traces show all three candidates assessed on each
response. The guard converted some baseline NLI accepts that ended in
`conflicting_accepted_answers` into explicit qualifier abstentions. It did
not turn any additional valid answer into a hit. One baseline request reached
`verification_budget_exhausted`; that contributes to the long tail.

The latency figures describe one sequential OFF-then-ON run on one Windows
machine. Startup varied by about three seconds, and model/cache warm state
and scheduling may differ. The fewer NLI calls provide a plausible mechanism
for shorter ON decisions here, but these data do not establish a repeatable
speedup. Controlled-provider calls are counts, not cloud cost savings.

**Recommendation: keep the guard experimental and off by default.** This
fresh live-path challenge has no observed safety or valid-reuse improvement
over the baseline, despite improved explanation of some abstentions. The
earlier fixed-candidate result remains promising development evidence, not a
reason to enable this for deployment or the normal demo. The known extraction
gaps and low valid reuse need a separate justified improvement and new
disjoint validation. No threshold was changed for this challenge.

`results_complete/` contains the row-level HTTP responses, candidate traces,
readiness snapshots, latencies, summary, trace analysis, and manifest. The
initial `summary.json` field named `verification_abstentions` counts all
misses after assessment, including explicit rejections; the separately
generated `trace_analysis.json` gives the narrower 10 request abstentions.
`results/` is a
retained failed first attempt: its requests completed, but the summary writer
raised a `TypeError`; those rows were not used for the reported comparison.
