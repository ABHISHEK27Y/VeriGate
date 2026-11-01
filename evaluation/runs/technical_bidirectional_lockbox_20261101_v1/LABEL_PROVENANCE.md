# Controlled technical answer-reuse lockbox

These 30 labels and their short contracts were authored and frozen before any
policy or model run on this workload. They are **independent of NLI scores** and
are based on the stipulated operation, target, environment, version, permission,
or code identifier in each stored question and answer. A valid row requests the
same operation with the same material parameters. An invalid row changes a
material operation or parameter. An abstain row omits information needed to
decide whether the specific cached answer applies. The individual contract in
`workload.json` explains each judgement.

The families and question strings are disjoint from the earlier 10-family
technical NLI comparison and the technical-identity v2 workload. The set
includes commands and code, a deliberately long answer, version changes,
permissions, ambiguous requests, and valid wording variations. Some commands
are controlled illustrative procedures, not a certification of external system
documentation or operational safety. This evaluation tests reuse against the
stipulated answer; it does not prove factual correctness, population error
prevalence, or production safety. Ambiguous rows are reported separately and
excluded from the binary invalid denominator.
