# Frozen live-path applicability labels

This authored controlled workload has five technical families, 15 cached
question/answer candidates, and 25 probes. Every probe states the specific
candidate indices whose answer is suitable, or an empty list. The suitability
contract in `workload.json` was written before either gateway variant ran.
Labels are based on the stipulated task and answer text, independently of model
scores; they are not human-reviewed production answers or traffic prevalence.

Each probe has three competing candidates. Valid means one specified candidate
answers the incoming task. Invalid means none does because action or target
conflicts. Ambiguous means a necessary target or environment is absent, so the
expected policy response is abstention. The Docker scan omission is deliberately
valid because that cached answer says the read-only procedure applies in every
environment. Candidate order and labels are identical for OFF and ON.

The input SHA-256 and evaluation settings are in `freeze.json`. This set is
disjoint in question families from the earlier fixed-candidate applicability
workload. It remains a small authored test, not an estimate of arbitrary
technical-query accuracy.
