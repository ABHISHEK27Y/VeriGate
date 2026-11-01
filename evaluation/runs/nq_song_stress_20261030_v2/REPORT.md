# Frozen 1,000-request controlled-answer HTTP stress evaluation

Source: [NQ-Open train](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open), CC BY-SA 3.0. The questions and answers are derived from NQ-Open; three paraphrases and one entity-swap hard negative per family are authored transformations.

**Label limit:** These are authored controls against NQ short answers, not independently human-reviewed answer validity. NQ references can omit co-writers. A mismatch is a suspected incorrect acceptance requiring source review. This workload is not representative production traffic.

Workload SHA-256: `2ab1c4b696e7acd184278816b2fe194cd8aa3987a7c6f6e22ea9dd55d5e0158f`. Policy SHA-256: `f9d2365021192fe7a78c54a0d250e1c384f416ad3c1818b084c5b89cd276b6a2`. Seed: 90210. No thresholds were retuned after the run.

| Capacity | Policy | Completed | Correct hits | Suspected wrong hits | Live opportunities | Hits/live | Hits/common potential | Unnecessary provider calls | Provider calls | Warm HTTP p50 / p95 / p99 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| sufficient | exact | 1000/1000 | 0 | 0 | 788 | 0.0 | 0.0 | 788 | 1000 | 35.125 / 46.123 / 88.269 (n=999) |
| sufficient | static | 1000/1000 | 0 | 0 | 788 | 0.0 | 0.0 | 788 | 1000 | 116.915 / 197.651 / 318.965 (n=999) |
| sufficient | answer_aware | 1000/1000 | 682 | 54 | 740 | 0.9216 | 0.8525 | 58 | 264 | 198.681 / 363.501 / 617.626 (n=999) |
| deployment | exact | 1000/1000 | 0 | 0 | 599 | 0.0 | 0.0 | 599 | 1000 | 37.239 / 43.992 / 77.084 (n=999) |
| deployment | static | 1000/1000 | 0 | 0 | 536 | 0.0 | 0.0 | 536 | 1000 | 130.076 / 228.822 / 369.601 (n=999) |
| deployment | answer_aware | 1000/1000 | 682 | 54 | 740 | 0.9216 | 0.8525 | 58 | 264 | 187.456 / 337.994 / 474.662 (n=999) |

Startup and first-request times (ms):

| Capacity | Policy | Startup | First HTTP | NLI invocations |
|---|---|---:|---:|---:|
| sufficient | exact | 5080.56 | 44.523 | 0 |
| sufficient | static | 81183.658 | 102.862 | 0 |
| sufficient | answer_aware | 81705.184 | 93.036 | 917 |
| deployment | exact | 5030.227 | 41.769 | 0 |
| deployment | static | 75688.219 | 106.295 | 0 |
| deployment | answer_aware | 75628.851 | 157.529 | 917 |

The common potential-reuse denominator is 800 requests: an earlier question in the frozen order had the same controlled reference answer. Live-cache opportunities vary by policy and capacity; both denominators are shown.

The latency rows report a single sequential local runner, not concurrent throughput. Cold startup is separate from the first HTTP request. Per-request gateway lookup, admission, provider, and cache-write stages are in `requests.csv` as `stage_latency_ms`.
Family-bootstrap 95% descriptive intervals for controlled-label reuse and suspected wrong-hit rates are in `aggregate.csv`. They measure sampling variability across these 200 authored families, not uncertainty from incomplete NQ answers or production traffic.

Inspect `by_category.csv`, `by_distance.csv`, `all_suspected_incorrect_accepts.csv`, and `failure_examples.csv`. Distance is the gap from the previous same-family request; it is not necessarily the distance from the nearest suitable cached answer.

A miss is unnecessary only when a suitable controlled answer existed in live Redis immediately before the request. An exact-cache miss on a new text can therefore count as a lost reuse opportunity. Hard negatives can legitimately reuse a different family’s cached answer.
