# Interpretation of this preserved run

This completed first pass used a fixed 0.72 similarity threshold **with** the
gateway's token-diff structural verifier for the run labelled `static` in its
CSV files. It is a static-plus-verifier ablation, not the repository's pure
static-threshold baseline. The incorrect configuration was found after the
run; none of its requests, labels or outputs were rewritten.

The [v3 run](../nq_song_stress_20261030_v3/REPORT.md) uses the same frozen
1,000-question workload with the intended static threshold **without** the
structural verifier. Use v3 for the three-policy comparison. This v2 run is
retained to show the diagnostic failure and for reproducibility.
