# Seven earlier valid misses: development diagnosis

These rows come from the older fixed-candidate 32-case workload, not this new
live-path challenge. Their stored answer was stipulated suitable for each
incoming question. All seven candidate similarities exceeded the unchanged
0.35 retrieval floor; there was no truncation. Five reached NLI, and two
abstained before NLI in the experimental applicability check.

| Family / incoming form | Similarity | Stage and saved reason | NLI score |
|---|---:|---|---:|
| Ansible `plan ... host atlas` | .801 | NLI rejected `answer_contradiction_or_irrelevance` | .157 |
| Ansible `way to preview ... host atlas` | .995 | NLI `uncertain_answer` | .812 |
| Vault `give read permission ... secret/team` | .956 | NLI `uncertain_answer` | .542 |
| Vault `What policy gives ... read access` | .840 | applicability `action_missing` | not called |
| Systemd `reboot ... server north` | .971 | NLI `uncertain_answer` | .219 |
| Systemd `command restarts ... server north` | .885 | applicability `action_missing` | not called |
| Playwright `way to run ... marked smoke` | .984 | NLI `uncertain_answer` | .890 |

The two extraction abstentions reflect unsupported inflected/grammatical
action forms (`gives`, `restarts`), despite a suitable answer. The other five
are NLI model/wording uncertainty or rejection at frozen thresholds. Because
these are inspected development cases, no rule, threshold, or model was
changed to fit them. The new challenge uses disjoint question families.

The first run in `results/` completed its requests but its summary writer
raised a `TypeError` while counting verification abstentions. It is retained
as a failed attempt. `results_complete/` is the separate complete rerun using
the same frozen workload and corrected aggregation.
