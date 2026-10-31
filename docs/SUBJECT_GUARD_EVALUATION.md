# Named-work identity safeguard: measured checkpoint

The opt-in answer-aware policy now compares **explicitly named works** before
asking NLI to authorize reuse. It recognizes typed song, album, book/novel,
film/movie, poem, painting, and play titles. Case, punctuation, film/movie,
book/novel, and a leading `the` are normalized. Different parsed works cause
`answer_reject:subject_identity_conflict` and a normal provider call. Unknown
question forms still follow the existing policy. Exact caching remains the
deployment default.

## Why the stress run failed

The [row-by-row audit](../evaluation/analysis/subject_guard_20261030_v1/all_54_failure_audit.csv)
inspected **all 54** suspected wrong accepts in the frozen
`nq_song_stress_20261030_v3` answer-aware sufficient-capacity run. Cause groups
overlap: all 54 selected a different explicit song, passed the earlier
number/negation/scope checks, and received an NLI score above the unchanged
accept threshold. One pair has a title-prefix ambiguity that merits source
review. Incomplete NQ short references or incorrect labels remain unresolved
for all 54 without independent adjudication; these are suspected answer errors,
not human-reviewed wrong-answer counts. See the [audit explanation](../evaluation/analysis/subject_guard_20261030_v1/AUDIT.md).

For example, the incoming question about **“You're the One That I Want”**
selected a cached question about **“All I Want Is You.”** MiniLM similarity was
0.666, above the artifact's retrieval floor. Both asked for a song writer, so
the old structural checks passed. NLI assigned 0.990 entailment to generic
assertions using the cached answer “U2's,” and the gateway served it; the NQ
reference for the incoming song is “John Farrar.” The new guard detects two
different named songs before that NLI call. This is a retrieval confusion
followed by a verifier false acceptance, not evidence that NLI knows the song
writers.

## HTTP comparisons

All runs used real HTTP, Redis Stack, pinned MiniLM and NLI, an isolated
controlled-answer provider, and the same answer-policy artifact and thresholds.
The [original workload](../evaluation/runs/nq_song_stress_20261030_v3/REPORT.md)
and its results remain unchanged.

| Evidence | Mode | Requests | Reference-matching hits / live opportunities | Suspected wrong hits | False rejections | Provider calls |
|---|---|---:|---:|---:|---:|---:|
| Inspected song development run | Unchanged | 1,000 | 682 / 740 | 54 | 58 | 264 |
| [Separate guarded development rerun](../evaluation/runs/nq_song_guard_development_20261030_v1/answer_aware_sufficient/requests.csv) | Guarded | 1,000 | 726 / 788 | 0 | 60 | 274 |
| [First new-entity set, parser defect](../evaluation/runs/subject_guard_holdout_20261030_v1/comparison.csv) | Unchanged | 120 | 83 / 84 | 0 | 1 | 37 |
| First new-entity set, parser defect | Guarded | 120 | 42 / 84 | 0 | 42 | 78 |
| [Second fresh four-domain set](../evaluation/runs/subject_guard_holdout_20261030_v2/comparison.csv) | Unchanged | 100 | 73 / 75 | 0 | 2 | 27 |
| Second fresh four-domain set | Guarded | 100 | 73 / 75 | 0 | 2 | 27 |

The first new-entity set found a general parser defect: “For the film X, name
its director” was parsed as though `name its director` were part of the title.
Its run is preserved as development evidence. The clause-boundary fix has a
regression test; the second set was frozen with **25 new entities**, disjoint
from the first set and the 200-song stress run, before either mode ran. It has
books, films, poems and songs; [freeze.json](../evaluation/runs/subject_guard_holdout_20261030_v2/freeze.json)
records source lines, hashes, model revisions, configuration and seed. Every
reference remains an authored control derived from NQ-Open, with possible
missing aliases or co-creators. The 100 uncertain reference rows are recorded
as such and must not be described as independently verified correctness.

The [saved per-position comparison](../evaluation/runs/nq_song_guard_development_20261030_v1/position_comparison.csv)
shows that, on the inspected development sequence, 679 of the original 682
reference-matching hit positions remained hits. Two became NLI false
rejections and one retrieved a different song after the cache evolved; the
originally served answer at that position is not proof of subject equivalence.
Of the 54 old suspected wrong positions, 31 became reference-matching hits,
21 cold misses, and two false rejections. The cache states diverge, so these
are descriptive position comparisons, not matched-candidate causal rates.

The fresh set showed **no wrong accepts in either mode**, so it establishes no
measured error reduction on fresh entities. It does show that the corrected
guard retained all 73 baseline matching hits and the same 73/75 live reuse
coverage on this bounded set. It cannot rule out errors elsewhere.

## Limit

This guard is a bounded syntax safeguard, not an entity-linking system. It
cannot verify an unsupported title alias, a subject expressed without a typed
work phrase, or the factual correctness of a provider answer. The NLI model
still cannot reliably authorize broad factual reuse by itself. Semantic mode
remains experimental; keep `CACHE_MATCH_MODE=exact` for deployment defaults.

To reproduce the fresh comparison with a new run ID, use
`python -m scripts.evaluate_subject_guard_http build <new-directory>`, then
`run` and `analyze` with that directory. The saved v1 and v2 runner snapshots
preserve the exact code used for their immutable outputs.
