# Frozen subject-identity challenge (2026-10-30)

This is a **controlled fictional catalog**, not a test of real-world answer
correctness. It was created and hashed before either HTTP policy run. The
[freeze](freeze.json) records the 41-question workload hash
`e52ff01d05ca08ba307da97a8a8d650b29f4e6dd523679aa7b92d000551a4dca`,
catalog hash, provider-answer hash, and unchanged answer-policy artifact hash.
All 41 rows retain their stipulated answer, evidence, and uncertainty in the
[workload](workload.csv). The eight named-work families use previously unseen
fictional songs, books, films, and poems. Three more families ask about a person,
place, or date outside the guard's supported syntax. Each family has a valid
paraphrase and a different-identity near match; named-work families also have a
declared title variation. Earlier workloads were checked for overlapping seed
titles. No challenge result was used to change the policy or thresholds.

Both runs used a disposable local FastAPI gateway over HTTP, Redis Stack
RediSearch, pinned MiniLM embeddings, pinned NLI, the same controlled-answer
provider, and separate namespaces. There were no paid calls. Full row decisions,
retrieved queries, answers, reasons, similarities, stage and HTTP times are in
[unchanged requests](answer_aware_unchanged/requests.csv) and
[guarded requests](answer_aware_guarded/requests.csv). The [comparison](comparison.json)
is derived from those saved observations.

| Measure | Unchanged | Guarded |
|---|---:|---:|
| Completed HTTP requests | 41/41 | 41/41 |
| Incorrect accepts against catalog / invalid near matches | 7/11 | 0/11 |
| Valid reuse retained / valid opportunities | 19/19 | 18/19 |
| Unnecessary rejection of a valid candidate | 0 | 1 |
| Provider calls | 15 | 23 |
| Median HTTP time, ms | 98.342 | 79.948 |
| P95 HTTP time, ms | 167.586 | 132.864 |
| Median gateway time, ms | 94.390 | 77.040 |
| Cold startup, ms | 75,628.098 | 35,290.388 |

The seven unchanged incorrect accepts were all different named works with
similar titles. The guarded policy rejected them. The single lost valid reuse
was `work-03:title_variation`: the catalog declares “A Lantern in Winter” and
“Lantern in Winter” the same book, but the parser retains leading `a` and
reports `subject_identity_conflict`. This failure is preserved in the rows.
The guard also rejects an otherwise valid question when an attribution phrase
such as “by The Larks” follows a typed title, because it treats the entire
phrase as title text. Such extraction is unsupported. Removing `a` or `by ...`
without reliable title boundaries could merge truly distinct works, so this
checkpoint does not retune the parser on these challenge results.

The person/place/date cases did not produce incorrect accepts in either mode;
the named-work guard did not add coverage for them. Unknown title syntax such
as “Who wrote Glass Harbor?” is likewise outside this guard. Case, punctuation,
book/novel, film/movie, and a leading `the` variation are supported as syntax
normalizations, but they are not a general alias database. Fictional stipulated
answers establish whether the gateway obeys this catalog, not whether its NLI
is factually accurate. The two latency distributions include different cache
states and run order; they do not show that the guard makes inference faster.
Startup was measured separately. Exact matching remains the deployment default
and answer-aware semantic matching remains experimental.

To reproduce with a **new** directory (never overwrite this evidence):

```powershell
python -m scripts.challenge_subject_guard_http build evaluation/runs/NEW_ID
python -m scripts.challenge_subject_guard_http run evaluation/runs/NEW_ID
python -m scripts.challenge_subject_guard_http analyze evaluation/runs/NEW_ID
```
