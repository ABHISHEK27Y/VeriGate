# Shadow answer review (experimental)

`SHADOW_ENABLED=false` and `SHADOW_SAMPLE_RATE=0` keep this feature off by
default. With both enabled, a sampled cache HIT returns its cached answer
immediately while a bounded background task asks the configured provider for a
fresh answer. This makes **an additional provider request** for each sample;
real providers may charge for it. It is not included in the current daily
request-admission budget. A Redis-backed `SHADOW_DAILY_LIMIT_PER_TENANT`
(default 20; zero disables all fresh calls) caps sampled upstream calls per
tenant per rolling 24-hour window. The process cancels unfinished samples at
shutdown.

Each sample is stored in Redis under the current cache namespace and tenant:
`<namespace>:shadow:review:<tenant_id>`. The Redis list is capped by
`SHADOW_REVIEW_LIMIT` (default 100) and expires after `CACHE_TTL_SEC`. The
record includes the incoming prompt, cached query, cached answer, fresh answer, provider, timestamp,
and an opaque ID. It has `review_status: unreviewed` and `label: null`.
These records contain user content: restrict Redis access and handle exports
as sensitive data. A separate offline local-model judge script exists, but
its first gold validation failed; it is not an online correctness decision
or a review endpoint. A different answer is a disagreement, **not** proof that the
cached answer was wrong; even an identical answer is not proof of correctness.

The sampler caps in-flight work with `SHADOW_MAX_PENDING` (default 4), applies
the normal provider timeout and response-length limit, and increments
`verigate_shadow_total{outcome=scheduled|recorded|failed|budget_exhausted}`. Failures are
counted without changing the user response. Since it is in-process and
best-effort, it is not a durable audit queue. Records exceeding
`MAX_CACHE_ENTRY_BYTES` are discarded. The proposed Phase 4 controller
must wait for independently reviewed labels and a drift evaluation.

`python -m scripts.judge_answer_reuse` validates a pinned local triple judge
against NQ oracle factoid labels. Only unlabelled records with a nonblank
cached query and cached answer are eligible for optional `model_judged`
output. The existing 2,000-row QQP/PAWS review queue has blank cached
answers, so it yields no judge labels. `--shadow-tenant TENANT` opts into
reading a Redis shadow queue. Neither model opinions nor blank queue rows
are counted as gold evidence. See `RESULTS_EXPERIMENTAL.md` for validation.
