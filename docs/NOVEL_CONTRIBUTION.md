# VeriGate contribution: current, bounded claim

VeriGate is an LLM gateway with an exact cache by default and an opt-in semantic-cache
research path. Its current algorithms are engineering work and exploratory comparisons,
not a proven new caching method. [GPTCache, vCache and Krites](RESEARCH_BASELINE.md)
already cover parts of similarity thresholds, adaptation and verification.

The **candidate semester contribution** is a measured, interpretable policy that sends
uncertain answer-reuse candidates to a costlier verifier while handling easy accepts
and structural rejects cheaply. It would be new *within this project* if implemented
and fairly compared; no global novelty is claimed. The current gateway does **not**
have such a measured selective routing policy. Optional NLI runs after the structural
checks whenever enabled, and compares questions rather than the concrete answer.

## Current components

| Component | Actual behavior | Known limit |
|---|---|---|
| Adaptive threshold | Raises a heuristic similarity cutoff based on query features and neighbor density | No answer-specific correctness guarantee; fixed baseline needs fair tuning. |
| Token-diff verifier | Rejects changed numbers, negation, roles, content, and some tense/scope terms | Rejects many valid paraphrases; the capitalization version is a historical ablation. |
| Optional NLI | Checks bidirectional question entailment | Pretrained model, not an answer verifier; not selective by uncertainty. |
| Volatility rule | Bypasses keyword-matched time-sensitive prompts | Incomplete recall and possible false bypasses. |

The NQ study uses reference-answer strings, not independently reviewed cached replies.
The 124 specific-answer discrepancies in the [audit](../evaluation/results/answer_label_audit.json)
show why a query-pair label must not be called actual-answer correctness. Historical
strict and lenient results stay as proxy sensitivity studies; the lenient rule can
equate different people or dates. See [phase status](PHASE_STATUS.md) for what is open.

The earlier design rationale and historical claims are preserved in the
[archive](archive/NOVEL_CONTRIBUTION_HISTORICAL.md); they are not present-tense evidence.
