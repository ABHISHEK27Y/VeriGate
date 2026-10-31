# Frozen 1,000-request controlled-answer HTTP stress evaluation

Source: [NQ-Open train](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open), CC BY-SA 3.0. The questions and answers are derived from NQ-Open; three paraphrases and one entity-swap hard negative per family are authored transformations.

**Label limit:** These are authored controls against NQ short answers, not independently human-reviewed answer validity. NQ references can omit co-writers. A mismatch is a suspected incorrect acceptance requiring source review. This workload is not representative production traffic.

Workload SHA-256: `2ab1c4b696e7acd184278816b2fe194cd8aa3987a7c6f6e22ea9dd55d5e0158f`. Policy SHA-256: `f9d2365021192fe7a78c54a0d250e1c384f416ad3c1818b084c5b89cd276b6a2`. Seed: 90210. No thresholds were retuned after the run.
Static means fixed MiniLM cosine threshold 0.72 without the structural verifier; answer-aware means the frozen answer-policy artifact with NLI. Both use the same RediSearch retrieval path. Exact mode remains the gateway default outside this evaluation.
Same-family request gaps: min 1, median 136, max 684; all 1,000 row positions and previous-family distances are in `workload.csv`.

| Capacity | Policy | Completed | Reference-matching hits | Suspected wrong hits | Live opportunities | Hits/live | Hits/common potential | Unnecessary provider calls | Provider calls | Warm HTTP p50 / p95 / p99 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| sufficient | exact | 1000/1000 | 0 | 0 | 788 | 0.0 | 0.0 | 788 | 1000 | 35.193 / 51.006 / 87.449 (n=999) |
| sufficient | static | 1000/1000 | 712 | 90 | 712 | 1.0 | 0.89 | 0 | 198 | 63.894 / 142.934 / 200.787 (n=999) |
| sufficient | answer_aware | 1000/1000 | 682 | 54 | 740 | 0.9216 | 0.8525 | 58 | 264 | 211.609 / 364.226 / 547.796 (n=999) |
| deployment | exact | 1000/1000 | 0 | 0 | 599 | 0.0 | 0.0 | 599 | 1000 | 37.461 / 49.26 / 73.375 (n=999) |
| deployment | static | 1000/1000 | 712 | 90 | 712 | 1.0 | 0.89 | 0 | 198 | 65.388 / 138.863 / 220.001 (n=999) |
| deployment | answer_aware | 1000/1000 | 682 | 54 | 740 | 0.9216 | 0.8525 | 58 | 264 | 205.338 / 385.625 / 662.32 (n=999) |

## What the rows show

The answer-aware policy reduced suspected wrong hits from 90 to 54 compared with the static threshold, while serving 682 reference-matching hits. It made 264 controlled-provider calls versus 198 for static. The 58 answer-aware verifier false rejections are lost reuse against the authored references. These observations do not establish real-answer correctness.
Exact caching had zero hits because every text is unique. Its live reuse opportunities fell from 788 to 599 under the 256-entry deployment cap. Static and answer-aware outcomes were unchanged between capacity settings on this particular sequence.

### By question form (sufficient capacity)

| Policy | Form | Reference-matching hits | Suspected wrong hits | Verifier false rejections |
|---|---|---:|---:|---:|
| static | hard_negative | 140 | 19 | 0 |
| static | original | 148 | 16 | 0 |
| static | paraphrase_1 | 142 | 18 | 0 |
| static | paraphrase_2 | 140 | 18 | 0 |
| static | paraphrase_3 | 142 | 19 | 0 |
| answer_aware | hard_negative | 132 | 11 | 10 |
| answer_aware | original | 145 | 11 | 10 |
| answer_aware | paraphrase_1 | 137 | 13 | 11 |
| answer_aware | paraphrase_2 | 130 | 7 | 18 |
| answer_aware | paraphrase_3 | 138 | 12 | 9 |

All three authored paraphrase forms produced both reference-matching reuse and suspected wrong reuse. The fronted 'For the song ...' form had the most answer-aware false rejections. Every suspected wrong acceptance is in `all_suspected_incorrect_accepts.csv`; `failure_examples.csv` also includes concrete unnecessary misses with selected candidates, answers and reasons.

Examples of suspected wrong acceptance from the sufficient-capacity answer-aware run:

- Incoming: “Name the writer of the song this i promise you.” Cached question: “For the song i'll see you in my dreams, who is credited as its writer?” Served: “Isham Jones”; NQ reference: “pop singer Richard Marx”.
- Incoming: “Who wrote the song you're the one that i want?” Cached question: “For the song all i want is you, who is credited as its writer?” Served: “U2's”; NQ reference: “John Farrar”.
- Incoming: “For the song try and catch the wind, who wrote it?” Cached question: “Who wrote the song take a walk on the wild side?” Served: “Lou Reed”; NQ reference: “British singer-songwriter Donovan”.

Startup and first-request times (ms):

| Capacity | Policy | Startup | First HTTP | NLI invocations |
|---|---|---:|---:|---:|
| sufficient | exact | 4163.412 | 38.792 | 0 |
| sufficient | static | 78228.735 | 93.087 | 0 |
| sufficient | answer_aware | 73098.277 | 107.112 | 917 |
| deployment | exact | 5049.921 | 39.06 | 0 |
| deployment | static | 73632.288 | 104.78 | 0 |
| deployment | answer_aware | 88287.421 | 172.213 | 917 |

The common potential-reuse denominator is 800 requests: an earlier question in the frozen order had the same controlled reference answer. Live-cache opportunities vary by policy and capacity; both denominators are shown.

The latency rows report a single sequential local runner, not concurrent throughput. Cold startup is separate from the first HTTP request. Per-request gateway lookup, admission, provider, and cache-write stages are in `requests.csv` as `stage_latency_ms`.
Family-bootstrap 95% descriptive intervals for controlled-label reuse and suspected wrong-hit rates are in `aggregate.csv`. They measure sampling variability across these 200 authored families, not uncertainty from incomplete NQ answers or production traffic.

Inspect `by_category.csv`, `by_distance.csv`, `all_suspected_incorrect_accepts.csv`, and `failure_examples.csv`. Distance is the gap from the previous same-family request; it is not necessarily the distance from the nearest suitable cached answer.

A miss is unnecessary only when a suitable controlled answer existed in live Redis immediately before the request. An exact-cache miss on a new text can therefore count as a lost reuse opportunity. Hard negatives can legitimately reuse a different family’s cached answer.
All 1,000 question texts are unique, so exact matching has no literal repeat to hit. Its zero-hit result measures the lack of semantic reuse on this workload, not exact-cache performance on repeated identical prompts.
