# Protocol for the next answer-reuse experiment

**Status: preregistration draft, not an executed final experiment.** The old NQ,
QQP, PAWS and smoke data have already been inspected while changing the policies.
Their results are development evidence. A final lockbox does not yet exist.

## Decision and labels

The decision is whether to serve one recorded answer to a new request under the
same tenant, context and answer version. The first study is short English factoid
answers. Reviewers label `reuse_ok`, `reuse_no` or `uncertain` for the **specific
recorded answer**. A public reference-string match, question paraphrase label,
synthetic rule and model judge are separate label types; none substitutes for a
reviewed answer. Exclude uncertain rows from binary rates and report their count.

## Split before model work

After obtaining reviewed examples, assign connected questions, near-duplicate
families and shared source/context to one split with a recorded seed. Persist row IDs,
group IDs and SHA-256 hashes. Train on training groups; choose policy parameters and
the empirical operating point on validation; reserve a distinct calibration part for
any risk-selection experiment. Open final test only once after freezing the policy,
baseline thresholds, metrics and code. Reject overlapping IDs and groups by script.
Previously inspected NQ pairs and their related families remain development-only.

## Primary comparison

At a validation-selected empirical incorrect-reuse target of 5%, compare **correct
accepted reuse per request** on final test. If a method has no feasible nonempty
validation point, report zero coverage and undefined served-risk. Also show risk at
matched coverage and complete descriptive risk–coverage curves. The 5% target is an
empirical comparison, not a formal safety guarantee.

Baselines: exact matching, tuned static similarity, old capitalization verifier,
token-diff, learned score without NLI, always-NLI, never-NLI and the proposed
selective method. Tune static thresholds on the same validation data and grid as
other policy thresholds. Count total candidates, accepted, correct accepted,
incorrect accepted, rejected, verifier calls and upstream calls. Report end-to-end
latency separately from verifier inference and model load. Use grouped bootstrap
intervals over independent question families; when zero errors are observed,
include an exact one-sided binomial upper bound only if the sampling assumptions
are justified. Never present a bootstrap [0,0] as zero population error.

Five seeds are overlapping partitions of the same corpus, not five independent
datasets. Show every split and then descriptive means. Do not pool label types.
Finite-grid risk control on mined correlated pairs is a diagnostic simulation;
its IID guarantee does not transfer automatically to production requests.

## Reproduction gate

Record the source and derived file hashes, split manifest, model name and revision,
feature settings, policy version, random seeds, command, Python and package versions,
CPU/GPU and elapsed time. Store each run under a new immutable run ID. Reports must
reject mismatched manifests. No final-model training begins until the reviewed labels
and split validation pass.
