# Frozen stress-run failure audit

All 54 suspected wrong accepts in the sufficient-capacity answer-aware run are listed in `all_54_failure_audit.csv`. Cause groups overlap.

- Different explicit named work and nearest-neighbour retrieval confusion: 54/54.
- Earlier number, negation and scope checks passed: 54/54.
- NLI accepted the conflicting answer assertion: 54/54.
- Possible title-prefix ambiguity needing source review: 1/54.
- Incomplete NQ references or incorrect labels: unresolved for all 54 without independent answer adjudication. No count is claimed for either.

Retrieval returns the nearest MiniLM question even when its named work differs. The old structural checks cover numbers, negation and scope, but not work identity. NLI then scores the two generic answer assertions as entailing and authorizes the cached answer. A high NLI score here is evidence of verifier failure on subject conflict, not evidence that the NQ reference is complete. The new guard blocks an explicit work conflict before NLI while leaving unknown forms to the existing policy.
