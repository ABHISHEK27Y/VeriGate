# VeriGate documentation index

Start with [the learning guide](VERIGATE_LEARNING_GUIDE.md) for concepts, then read
[the current research baseline](RESEARCH_BASELINE.md) before using any result in a
presentation. For the running system, use [production configuration](PRODUCTION_CONFIGURATION.md)
and [architecture](ARCHITECTURE_PRODUCTION.md). The [audit](audit/AUDIT_REPORT.md)
records historical findings and their remediation; its old open counts are not the
current release status.

The [evaluation harness](../evaluation/README.md) describes the smoke fixture and the
[generated pair-label results](RESULTS_V2.md) show the newer held-out proxy evaluation.
The [experimental model, replay and risk study](RESULTS_EXPERIMENTAL.md) records
further work without presenting it as answer-cache correctness.
The [NQ-Open dev MiniLM pilot](RESULTS_REALISTIC_PILOT.md) reports unlabelled
real-query decisions and warm local latency under a frozen answer policy.
The [close-neighbor diagnostic](RESULTS_CLOSE_NEIGHBOR.md) compares frozen
policies on NQ reference-string proxies and the later scope/direction fix.
The [live real-path results](RESULTS_LIVE_REAL_PATH.md) contain Redis Stack,
MiniLM/NLI, and two-worker HTTP measurements plus real-provider smoke prerequisites.
The [shadow review sampler](SHADOW_REVIEW.md) is an opt-in way to collect
fresh/cached answer pairs for independent review.
The [results log](RESULTS_LOG.md), [older evaluation plan](EVALUATION_PLAN.md), and
[earlier novelty proposal](NOVEL_CONTRIBUTION.md) contain historical hypotheses and
illustrative measurements. They are retained for provenance, not final evidence.
The [LaTeX report](../report/report.tex) is being revalidated; regenerate its numerical
tables with `python scripts/export_report_tables.py` after regenerating the CSVs.

For implementation detail, see [the code walkthrough](CODE_WALKTHROUGH.md),
[technology choices](TECH_STACK.md), and [deployment guide](DEPLOYMENT.md).
