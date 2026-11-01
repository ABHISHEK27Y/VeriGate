# VeriGate independent review — snapshot `37dc7a7`

Reviewer: static inspection only. Nothing was executed, edited, installed, or restarted.

---

## 1. Snapshot and review coverage

### Snapshot

| Item | Value |
|---|---|
| Branch | `codex/evaluation-integrity` |
| Commit (review baseline) | `37dc7a7400c1811cbf501d596d3535286ce81e17` — "Align pinned CI lint and stabilize streaming deadline regression" |
| Working tree at the start of the review | Clean except one untracked directory, `audit/` (previous-audit evidence logs). Treated as outside the snapshot. |
| Working tree during the evaluation-scripts pass (latest) | Drift continued. `app/main.py` is now modified too (+32 lines, streaming `meta` parity — reviewed, see F19), along with `docs/CLAUDE_REVIEW_LEDGER.md` and `evaluation/runs/release_http_20261101_v1/` as new untracked paths. `evaluation/` and `scripts/` source files were **unmodified** throughout this pass, so F16–F18 describe the current tree. `HEAD` is still `37dc7a7`. |
| Working tree during the F2/F3 verification pass | **The other agent began editing mid-review.** `HEAD` is still `37dc7a7`, so the baseline is unchanged, but the tree also carries uncommitted modifications to `app/static/dashboard.html` (+34/−21), `tests/test_dashboard_private_chip.py`, `docs/ORG_WORKSPACE.md`, all seven `report/chapters/*.tex` and `report/report.{tex,bib,pdf}`, plus new untracked `report/RECONCILIATION.md`, `report/REVISION_EVIDENCE.md`, `report/chapters/A_Historical_Proxy.tex`, `report/revision_original_37dc7a7/`, `tmp/` and six `.pytest_tmp_*` directories. Per the brief these are a separate, unfinished implementation. The dashboard, its test and `ORG_WORKSPACE.md` **were** re-reviewed on request — see "Uncommitted dashboard work" after F14, which supersedes the dashboard rows in §4 and adds F15. The LaTeX report revision was not reviewed. Every other reviewed runtime file — all of `volatility.py`, `verifier.py`, `answer_policy.py`, `semantic_cache.py`, `storage.py`, `main.py` — is confirmed unmodified, so F1–F14 still describe the current tree. None of these changes are mine; my only writes were to this report outside the repository. |
| Stashes | none |
| Remote | `https://github.com/ABHISHEK27Y/VeriGate.git` |
| Local vs GitHub | `codex/evaluation-integrity` == `origin/codex/evaluation-integrity` (both `37dc7a7`). **Local `main` (`630269b`) differs from `origin/main` (`2a092f0`)** — the version reviewed is the branch, not `main`. |
| Repository instruction files | None found (no `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `.cursorrules`). Conventions were taken from `README.md`, `PROJECT_PROGRESS.md`, `docs/`. |
| Size | 624 tracked files; 7,055 LOC in `app/`, 5,539 in `tests/` |

### Reviewed in full

- **All 44 tracked files under `app/`** (every first-party runtime module), read line by line, except `app/static/dashboard.html`, which was reviewed by targeted inspection of its health-handling and result-rendering paths (lines ~190–445) rather than every line of CSS.
- `app/cache/artifacts/answer_policy_v1.json`, `config/organizations-demo.json` (key digests redacted before display), `.env.example` (filtered), `pytest.ini`, `pyproject` deps via `requirements.txt`, `.github/workflows/ci.yml`, `tests/conftest.py`.
- `evaluation/datasets.py`, `evaluation/protocol.py`, `scripts/evaluate_live_combined.py` (lines 1–280).
- Tests: full inventory of all 44 files and every test function name; read in full: `conftest.py`, `test_nli_input_bounds.py`, `test_freshness_rules.py`.
- Saved evaluation artifacts: `technical_applicability_live_20261101_v1/` (`FINDINGS.md`, `VALID_MISS_DIAGNOSIS.md`, `LABEL_PROVENANCE.md`, `DEVELOPMENT_MISSES.md`, `freeze.json`, `workload.json`); `technical_combined_fresh_20261101_v1/` (`results/summary.json`, `nli_memory.json`, `redis_shortlist_benchmark.json`); `technical_bidirectional_lockbox_20261101_v1/` (`FINDINGS.md`, `results/summary.json`); `freshness_dev_20261030_v3/` (`summary.json`, `decisions.csv`); `evaluation/dev/freshness_cases_v1.tsv`.
- Docs: `README.md` (1–80), `PROJECT_PROGRESS.md` (1–120), `docs/PHASE_STATUS.md` (freshness/safeguard section), `docs/ORG_WORKSPACE.md` (1–60).

### Not reviewed (explicit gaps)

- **9 of 18 `evaluation/*.py` modules**: `gold_model.py`, `gold_verifier_study.py`, `cascade.py`, `stream.py`, `stream_gold.py`, `reproduce.py`, `risk_guarantee.py`, `backend_compare.py`, `train_accept.py`. (Reviewed in a later pass: `run.py` in full, `latency.py` key paths, `gold_answers.py`, `benchmark.py` fixture contents, plus `datasets.py` and `protocol.py` from the first pass.)
- **51 of 60 `scripts/`**. Reviewed: `evaluate_live_combined.py`, `verify_live_combined.py`, `inspect_nli_window.py`, `export_report_tables.py`, `stress_semantic_http.py` (build, `classify`, `live_entries`, freeze), `analyze_stress_semantic_http.py` (aggregation, `family_interval`, report text), plus structural surveys of `build_answer_pairs.py` and `summarize_experiments.py`. The remaining unreviewed scripts are the per-experiment runners and analyzers for the subject-guard, pilot, judge, benchmark and provisioning workflows; the largest is `evaluate_subject_guard_http.py` (301).
- **40 of 44 test file bodies** (names and signatures only).
- ~170 saved CSV/JSON artifacts, all 36 `gateway.log` files, the 28-file LaTeX report and `report/report.pdf`, 38 of 42 docs, `Dockerfile`/compose/Grafana/Prometheus config, the untracked `audit/` tree (file names only).
- **Essentially nothing was executed.** Every finding below is static reasoning plus the project's own saved artifacts. Where a finding needs a run to confirm, it is labelled *suspected*.
  - One exception, added during the F2/F3 verification pass: `app/cache/volatility.is_volatile` was called directly in a throwaway interpreter to reproduce the saved freshness run. That module imports only `re`, and `app/__init__.py` and `app/cache/__init__.py` are docstrings only, so no configuration, model, Redis connection, or service was touched. The gateway was not started, pytest was not run, no package was installed, and nothing in the repository was written. Flagging it because the brief said not to run the application or tests.

This is therefore a complete review of the first-party runtime (`app/`) and of the technical-reuse evaluation evidence, and a partial review of the evaluation/tooling layer.

---

## 2. What works, and the principal blockers

### What works

The gateway is a real, carefully built system, not a prototype shell.

- **Authentication and tenancy.** Server-owned HMAC digests only (`organization.py:170–210`); no plaintext credentials in the directory, keys, or logs. Revocation takes effect immediately and is re-checked after a slow verifier and again after generation before publishing (`main.py:214–220, 750, 824`). Cache scopes are opaque HMACs that bind organization, scope, subject, application, provider profile, profile-compatibility digest, and route (`organization.py:252–277`). Cross-organization and cross-employee private isolation is enforced by key construction, not by filtering, and is covered by 19 tests in `test_organization_scopes.py`.
- **Authorized sharing actually works** for the demo shape: Alice and Carol, both `cache:shared` in `engineering` on the org default profile, resolve to the same `s_…` tenant and reuse each other's answers; Dave in `other` cannot request `engineering` (403 via `PermissionError`).
- **Request lifecycle.** A single `request_deadline_sec` budget is threaded through lookup, provider, and cache write; the provider must emit an explicit terminal event with `finish_reason == "stop"` or nothing is cached (`main.py:435–443`, `openai_compat.py:118–132`); truncated, duplicate-terminal, tool-call, and empty generations are all rejected and uncached. Cache-write failure never loses the generated answer. Budget is charged only on miss/bypass.
- **Storage.** Per-scope and per-organization entry/byte quotas with atomic `WATCH` transactions, Redis-clock expiry reconciliation, and a final candidate-identity recheck before serving (`semantic_cache.py:645–681`) so an entry replaced or expired mid-decision is not served. `redisearch_store.knn` re-reads each hash and discards any row whose tenant/query/answer changed after `FT.SEARCH`.
- **Evaluation discipline.** This is the strongest part of the project. Workloads and labels are committed before runs with SHA-256 freezes; `evaluation/protocol.py` reports explicit denominators, grouped bootstrap intervals, and refuses to invent precision for a reject-all policy; `evaluation/datasets.py:group_split` uses union-find over normalised queries *and* families, so transitive leakage across train/val/cal/test is prevented; CI re-runs five `verify_*` validators and fails on any diff in generated results.
- **Honest documentation.** `README.md`, `PROJECT_PROGRESS.md`, and the run `FINDINGS.md` files consistently state limitations, negative results, and the fact that semantic mode is experimental and off by default. I found no claim in those files that the code does not support.

### Principal blockers for the demonstration

1. **The answer-aware verifier does not work well enough on technical text to be the headline feature.** The project's own frozen live run reuses **4 of 15** valid opportunities with the shipping configuration; the newest combined-guard run reaches **8 of 15**, and the shipping configuration **accepts 3 of 10 deliberately underspecified requests** on a disjoint frozen set. All suitable candidates are retrieved — retrieval and top-k are fine. The loss is entirely in the accept decision (finding F1).
2. **The NLI formulation structurally cannot verify a realistic technical answer.** The answer text is embedded in *both* the premise and the hypothesis, so it is charged twice against a 512-token window. A measured 1,620-character procedure produced a 596-token pair and returned `context_too_long` → provider call, forever, for every probe against it. The break-even answer length is roughly 1,350–1,400 characters of clean prose and **much lower for code- or identifier-dense text**. Every live technical workload uses 61–99-character answers, so this never shows up there (F2, verified).
3. **The volatility gate permanently un-caches ordinary technical questions.** The project's own dev set records 6 of 12 stable queries falsely bypassed. Words like `current`, `score`, `price`, `live`, `latest`, `recent` are common in technical prose; any such query is never stored and never reused, in exact *and* semantic mode (F3).
4. **Defaults ship the weaker configuration.** Out of the box `CACHE_MATCH_MODE=exact`, `ANSWER_POLICY_ARTIFACT=""`, `VERIFIER_NLI=false`, and both technical guards off. The product goal describes semantic answer reuse as the central feature; the default build is an exact-prompt cache. This is deliberate and documented, but it means a demo must be run in a non-default configuration and must say so.

---

## 3. Prioritized findings

> **Superseded in part.** Section 7 (final review pass, 2026-11-01) corrects F6, F16, F18, F20 and F22, withdraws two recommendations, and records F10 as fixed in uncommitted work. Read §7 before acting on any of those.

Severity is relative to a B.Tech major-project demonstration and viva, not to a production launch.

---

### F1 — BLOCKER · model limitation + design tradeoff · low valid reuse and ambiguous acceptance

**Where** `app/cache/answer_policy.py:187–188` (assertion formulation), `:199–203` (thresholds), `app/cache/artifacts/answer_policy_v1.json` (`accept_at=0.9`, `reject_below=0.2`, `min_similarity=0.35`, `ambiguity_terms=["georgia","congo","springfield"]`).

**Triggering scenario** Seed `"How do I deploy the GitLab pipeline to staging?"` → `"Deploy the GitLab pipeline to staging using the staging deployment job."`. Ask `"What is the way to deploy the GitLab pipeline to staging?"`.

**Execution path** `main.py:chat` → `_bounded_lookup` → `semantic_cache._lookup:468` embeds → `:523` ranks (candidate at rank 1, similarity 0.9891) → `:522–560` `AnswerPolicy.precheck` passes → `AnswerPolicy.decide:187–203` builds premise `"The answer to <stored> is <answer>."` / hypothesis `"The answer to <incoming> is <answer>."` → entailment probability **0.887** < `accept_at` 0.9 → `VERIFY` → MISS → provider call.

**Consequence** The central feature declines a near-identical paraphrase. Aggregated over the frozen set: valid reuse 4/15 (guard off and on), and 11 valid misses split 5 `VERIFY` / 6 `REJECT`.

**Confirmed evidence**
- `evaluation/runs/technical_applicability_live_20261101_v1/FINDINGS.md` — 4/15 both variants, 0/5 invalid accepts, 21 provider calls, all 15 suitable candidates retrieved.
- `.../VALID_MISS_DIAGNOSIS.md` — per-row ranks, actions, and NLI scores for all 11 misses, including the 0.887 and 0.891 near-misses and six scores below 0.03 on valid paraphrases.
- `evaluation/runs/technical_bidirectional_lockbox_20261101_v1/FINDINGS.md` + `results/summary.json` — on 10 new families: shipping formulation 4/10 valid, **3/10 ambiguous accepts**; the reverse-assertion variant was worse (3/10 valid, same 3/10 ambiguous). The FINDINGS state the mechanism directly: "Repeating the same answer on both sides can make a specific answer look plausible for a broader request."
- `evaluation/runs/technical_combined_fresh_20261101_v1/results/summary.json` — baseline 6/15 valid, 1/5 ambiguous approvals; `ANSWER_POLICY_TECHNICAL_GUARD=true` + `ANSWER_POLICY_APPLICABILITY_GUARD=true` → 8/15 valid, 0/5 invalid, 0/5 ambiguous.

**Uncertainty** All denominators are 5–15 authored, single-annotator cases. 0/5 invalid accepts has a 95% one-sided upper bound near 0.52 — it is not a safety result. The 8/15-vs-6/15 improvement is 2 cases and is not significant.

**Smallest justified fix** Do **not** move thresholds (that would be tuning on inspected cases). Two honest options, in order of preference:
1. Run the demonstration with both experimental guards on (`ANSWER_POLICY_TECHNICAL_GUARD=true`, `ANSWER_POLICY_APPLICABILITY_GUARD=true`), which is the configuration with the best measured trade-off on a set frozen before the run, and label it experimental in the dashboard and the talk. Note the project's own prespecified promotion gate required three more valid hits and was not met, so this is a demo choice, not a promotion.
2. Keep defaults and present the low-reuse result as the measured finding it is.

**Regression needed** The acceptance protocol is already written in `VALID_MISS_DIAGNOSIS.md` ("One bounded verifier alternative to evaluate later"): a new family-disjoint frozen HTTP/top-k set with ≥150 valid, ≥150 invalid, 100 ambiguous probes, 95% binomial intervals, raw denominators, and three order-balanced timing runs. Adopt it unchanged.

---

### F2 — HIGH · **VERIFIED** implementation defect (formulation) · realistic answer lengths are unverifiable

**Where** `app/cache/verifier.py:335–355` (window check) against `app/cache/answer_policy.py:187–188` (the answer appears in premise **and** hypothesis).

**Triggering scenario** Cache `"How do I rotate the Postgres replication password?"` with a realistic 10-step, ~1,200-character answer (≈300 tokens). Ask any paraphrase.

**Execution path** `decide:187–188` builds two assertions each containing the full 300-token answer → `NliVerifier.assess:335–338` tokenizes the pair without truncation → `count ≈ 620` → `:342–355` `min(valid_limits) == 512` for `nli-deberta-v3-xsmall` → returns `too_long` → `decide:192–193` → `VERIFY` → provider call. This happens for **every** future paraphrase of that question, permanently.

**Consequence** Semantic answer reuse is structurally impossible for a cached answer above roughly 1,350–1,400 characters of clean English prose, and **far below that for code-, path-, flag- or identifier-dense text** — i.e. for exactly the content technical answers contain. `provider_max_completion_tokens` defaults to 2048, four times the verifier's entire window, so the gateway will routinely generate and store answers it can never afterwards verify.

**Confirmed evidence (verified 2026-11-01 against saved artifacts)**
- **Window = 512, executed by the project itself.** `evaluation/runs/nli_window_20261030_v2.json`: `tokenizer_limit: 512` for `cross-encoder/nli-deberta-v3-xsmall` revision `a150876…`, produced by `scripts/inspect_nli_window.py:19–20` from the real tokenizer.
- **Measured over-window case.** `technical_bidirectional_lockbox_20261101_v1/results_timed/decisions.csv`, family `long_config_answer`: stored answer **1,620 characters / 244 words**; `reason = context_too_long` on **all 6 rows** of that family — the valid, invalid *and* abstain probes, in both variants. `verifier_calls = 1`, `verifier_ms` 1.45–3.81, i.e. the tokenizer ran and inference did not. FINDINGS reports the pair at 596 tokens.
- **Comparison within the same run.** The other nine families' answers are 175–252 characters and every one was scored; only the 1,620-character family hit the window. Computed from the same CSV.
- **The window costs real valid reuse.** In the shipping variant, 6 of 10 valid probes missed, and `long_config_answer` is one of the six — `context_too_long` alone accounts for 1/10 of valid opportunities in a set containing a single long answer.
- **No single character ceiling exists.** `nli_window_20261030_v2.json` shows ~8× variation in tokens per byte with content alone: 499 bytes of `"xy "` → **655 tokens** (does not fit), while 659 bytes of `"123 "` → **335 tokens** (fits). The script's own comment states it: "byte count cannot stand in for the model's complete paired token sequence."
- **Live workloads cannot detect it.** Computed from `technical_applicability_live_20261101_v1/workload.json`: all 15 cached answers 61–99 characters (median 72), questions 37–60.
- `tests/test_nli_input_bounds.py` verifies the mechanism with a fake tokenizer (`WINDOW = 12`), never with the real pinned model.

**Residual uncertainty** The 1,350–1,400-character figure is extrapolated from **one** measured point (1,620 chars → 596 tokens ⇒ ≈270 tokens per answer copy ⇒ ≈5.9 chars/token, break-even ≈233 tokens per copy). The true boundary is content-dependent and, for code-dense answers, could be a few hundred characters. State the measured point, not the extrapolation, until step A2 measures the curve.

**Smallest justified fix** Three steps, none of which changes a threshold:
1. Record `input_tokens` (already returned by `NliAssessment`) in the candidate trace and in a histogram, so `too_long` is visible instead of silent.
2. Measure and **document** the applicable answer-length ceiling.
3. Only then consider a single-sided formulation (answer in the premise only) — that is a semantics change and needs its own frozen validation.

**Regression needed** A test on the **real pinned model** asserting that a >512-token paired input yields `context_too_long` without a prediction, and an assertion that the measured ceiling is recorded in the repo.

---

### F3 — HIGH · **VERIFIED (reproduced)** implementation defect · volatility gate permanently un-caches ordinary technical queries

**Where** `app/cache/volatility.py:137–193`; consumed at `app/cache/semantic_cache.py:396` (lookup → BYPASS), `:702` and `:726` (store → refuse), and `:315` (private overlay). The check at `:396` sits **before** the exact/semantic split at `:399`, so it applies in the default `exact` mode too.

**Triggering scenario** `"How do I get the current user in a Django request?"`

**Execution path** `_VOLATILE_RE` matches `current` → `_EXPLICIT_TIME_RE` does **not** contain bare `current` (only `currently`) → `_CONCEPT_REQUEST_RE` requires the query to start with `define`/`what does … mean`/`what is a(n)`/`what is the difference between`, which it does not → `is_volatile` returns `True` → lookup returns `BYPASS "volatile_query"` and `store` returns `False`. The question can never be cached and never be reused, in exact or semantic mode.

Other words with the same effect: `score`, `price`/`prices`, `temperature`, `stock`/`stocks`, `live`, `latest`, `recent`, `news`. E.g. `"How do I score a model in scikit-learn?"`, `"How do I live-reload nginx?"`, `"How do I get the latest commit hash in git?"`.

**Consequence** Demo-visible: any such prompt shows `BYPASS` and never produces a hit no matter how many times it is asked. It also silently removes those queries from every reuse denominator.

**Confirmed evidence (reproduced 2026-11-01)**
- **Saved run.** `evaluation/runs/freshness_dev_20261030_v3/summary.json`: `stable_n: 12`, `stable_bypassed: 6` — a 50% false-bypass rate on the project's own authored stable set. Documented in `docs/PHASE_STATUS.md`, so the limitation is known but has not been narrowed.
- **Independently re-executed** `is_volatile` over `evaluation/dev/freshness_cases_v1.tsv` at this commit: `stable_bypassed = 6/12`, `volatile_bypassed = 12/12` — an exact match to the saved summary. The six are `stable_04, 06, 07, 08, 11, 12`, each via the same branch (keyword matched, no explicit-time term, no concept opener).
- **Technical reproduction.** Of 12 realistic technical queries containing a volatility keyword, **12 of 12 bypass**, while two keyword-free controls ("How do I restart nginx gracefully?", "How do I rotate a Kubernetes service account token?") cache normally. Examples and the branch each takes:

  | Query | Keyword | Branch |
  |---|---|---|
  | How do I get the current user in a Django request? | `current` | no explicit time, no concept opener |
  | How do I compute an F1 score in PyTorch? | `score` | no explicit time, no concept opener |
  | What is the current working directory in a Dockerfile? | `current` | no explicit time, no concept opener |
  | How do I add a price field to a Postgres table? | `price` | no explicit time, no concept opener |
  | How do I list stock levels from the inventory API? | `stock` | no explicit time, no concept opener |
  | How do I set the CPU temperature threshold in a systemd unit? | `temperature` | no explicit time, no concept opener |
  | How do I get the latest commit hash in git? | `latest` | **`_EXPLICIT_TIME_RE` — unconditional** |
  | How do I live-reload nginx after a config change? | `live` | **`_EXPLICIT_TIME_RE` — unconditional** |
  | How do I fetch the most recent rows from a Kafka topic? | `recent` | **`_EXPLICIT_TIME_RE` — unconditional** |
  | How do I keep a dependency up to date with Renovate? | `up to date` | **`_EXPLICIT_TIME_RE` — unconditional** |

- **The technical evaluations cannot detect any of this.** Computed from the workload files: `technical_applicability_live_20261101_v1` and `technical_combined_fresh_20261101_v1` contain **no** volatility keyword at all.

**Smallest justified fix — corrected after reproduction.** My first recommendation (split into time references vs. value nouns, and require co-occurrence) fixes only the first six rows above. It does **not** help `latest`, `live`, `recent`, or `up to date`, because those four are themselves in `_EXPLICIT_TIME_RE:173–177` and bypass unconditionally at `volatility.py:190–191`, before any narrowing rule is consulted. The fix therefore needs two parts:
1. Make the value nouns (`price`, `prices`, `score`, `temperature`, `stock`, `stocks`, `current`, `news`) bypass only alongside a time reference or a possessive (`my`, `our`).
2. Move `latest`, `live`, `recent`, and `up to date` out of the unconditional `_EXPLICIT_TIME_RE` set and subject them to the same co-occurrence requirement, since each has a common non-temporal technical sense (`latest commit`, `live reload`, `recent rows`, `up to date dependency`). Keep `today`, `now`, `right now`, `tomorrow`, `yesterday`, `tonight`, `this week/month/year`, `as of` unconditional — those have no stable technical sense.

Validate against the existing 24 dev cases **plus** new technical cases; do not tune on the six inspected rows alone.

**Regression needed** Extend `evaluation/dev/freshness_cases_v1.tsv` with ≥12 technical stable cases (Django `current` user, scikit-learn `score`, git `latest` commit, nginx `live` reload, `price` field in a schema) and assert `stable_bypassed` does not regress on the existing 12.

---

### F4 — MEDIUM-HIGH · confirmed implementation defect · structural guards reject ordinary technical paraphrases before any model runs

**Where** `app/cache/answer_policy.py:27–47` and `:140–141` (`_scope_terms`), `:142–148` (yes/no openers).

**Triggering scenarios**
1. Stored `"What is a reliable way to restart nginx?"`; incoming `"What is the most reliable way to restart nginx?"` → `_scope_terms` `{}` vs `{"most"}` → `VERIFY "scope_changed"` → provider call, NLI never invoked.
2. Stored `"How do I enable TLS 1.3 on nginx?"`; incoming `"Can I enable TLS 1.3 on nginx?"` → incoming starts with `can`, stored does not → `REJECT "answer_type_mismatch"`.
3. Stored `"What is the only way to drop a Postgres column?"` vs incoming without `only` → `scope_changed`.

**Execution path** `_lookup:534–545` → `precheck` returns before the verifier gate, so the decision is final without any answer-level assessment.

**Consequence** `most`, `least`, `only`, `first`, `last` are ordinary technical English; superlative-vs-plain and polar-vs-procedural paraphrase are the two most common ways the same technical question gets re-asked. This is pure recall loss and it is cheap and invisible (no NLI score in the trace).

**Confirmed evidence** The guards are enabled whenever the policy artifact is set (`answer_policy_subject_guard` defaults `True`; the scope/opener checks are unconditional inside `precheck`). `technical_bidirectional_lockbox_20261101_v1/FINDINGS.md` lists `scope_changed` among the observed valid misses. `tests/test_answer_policy_live.py::test_changed_scope_abstains_without_nli` and `::test_equivalent_scope_words_reach_nli` lock the current behaviour in, so any change needs those updated deliberately.

**Uncertainty** The share of real technical traffic affected is unmeasured.

**Smallest justified fix** Restrict `_scope_terms` to ordinals/superlatives that appear in the **question head** (first four tokens) or that bind to a quantity, and restrict the yes/no-opener rejection to cases where the cached answer is not procedural. Both need their own frozen validation set — this is the second-highest-value recall work after F1.

**Regression needed** A frozen paraphrase set containing superlative-vs-plain and polar-vs-procedural pairs, with valid-reuse and incorrect-accept counts reported separately before and after.

---

### F5 — MEDIUM · confirmed implementation defect · `too_long` is never memoized and `unavailable` latches forever

**Where** `app/cache/verifier.py:355` (returns before the `self.cache[key] = result` at `:372`) and `:367–371` (`self.unavailable = True` on any exception, with no expiry); readiness consumer at `app/main.py:620–626`. Same two shapes in `app/cache/reuse_verifier.py:136, 145`.

**Triggering scenario A** A cached answer over the window is a top-5 candidate for a recurring question. Every request re-enters `assess`, re-runs the HF tokenizer on ~600 tokens **inside the global `threading.Lock`** and inside the `Semaphore(1)` verifier gate (`semantic_cache.py:73`), then returns `too_long` again. Repeated cost, zero information gained.

**Triggering scenario B** `ANSWER_POLICY_PREWARM` is false (the default). The first semantic request lazily loads the cross-encoder; a transient Hugging Face/network/disk error raises → `unavailable = True` for the process lifetime. From then on every candidate decision is `VERIFY "verifier_unavailable"` (every request calls the provider) **and** `/ready` returns 503 `"answer verifier unavailable"` permanently. Only a restart recovers.

**Consequence** B is a demo risk: one flaky model load on the venue network leaves a gateway that reports itself unready and never reuses anything, with no operator-visible way back.

**Confirmed evidence** Code paths above. `tests/test_audit_regressions.py::test_nli_unavailable_fails_closed` and `tests/test_policy_runtime_identity.py::test_readiness_reports_verifier_degradation` confirm the fail-closed behaviour is intended; neither tests recovery, because there is none.

**Smallest justified fix** (a) Store the `too_long` assessment in the memo before returning. (b) Replace the boolean latch with a failure count plus a cooldown timestamp, so the next request after the cooldown retries the load; keep fail-closed behaviour during the cooldown, and keep `last_failure_category` in `/ready`.

**Regression needed** Two tests: a repeated over-window pair calls the tokenizer exactly once; a single simulated transient load failure is retried after the cooldown and readiness recovers.

---

### F6 — MEDIUM · confirmed implementation defect · verifier memoization is bounded by entry count, not bytes

**Where** `app/cache/verifier.py:296` (`OrderedDict` keyed by `(scope, premise, hypothesis)`), `:314`, `:40` (`_MAX_NLI_PAIRS = 8192`), `:372–374` (count-based eviction). Same in `reuse_verifier.py:84, 98, 149`.

**Triggering scenario** A workspace accumulates near-the-limit entries: `max_cache_entry_bytes` defaults to 65,536, so one premise plus one hypothesis can hold ~130 KB of text. 8,192 such keys ≈ **1 GB of Python strings**, on top of the measured 680 MB model RSS.

**Execution path** Every distinct `(tenant, stored-question+answer, incoming-question)` triple adds one key; `purge_scope` only runs on an explicit `cache.clear(tenant)` (`semantic_cache.py:770`).

**Consequence** Unbounded-in-bytes growth for a long-lived process; OOM risk under a large shared workspace with long answers.

**Confirmed evidence** `evaluation/runs/technical_combined_fresh_20261101_v1/nli_memory.json`: `delta_bytes: 680878080` for the model alone. The memo bound is purely `len(self.cache) > 8192`.

**Uncertainty** Not reproduced; the technical workloads use 61–99-character answers, so the worst case has never been exercised.

**Smallest justified fix** Key the memo on `sha256(premise)`/`sha256(hypothesis)` instead of the text, and/or track summed key bytes and evict against a configured cap.

**Regression needed** A test that inserts large synthetic pairs and asserts the memo's byte footprint stays under a configured ceiling.

---

### F7 — MEDIUM · confirmed · duplicate work on the miss path and a JSON/streaming parity gap

Four related items in one finding, because one fix pass covers them.

**7a. Streaming has no request coalescing.** `app/main.py:854` wraps provider generation in `SingleFlight` for `/v1/chat` only. `chat_stream` (`:913–1110`) calls `registry.route_events` directly at `:958`. Ten concurrent identical streaming misses make ten provider calls; the same ten on `/v1/chat` make one. Documented asymmetry (`app/singleflight.py:1` says "JSON cache misses"), but it is a real parity gap and the streaming path is the one a live demo uses.

**7b. Every semantic miss embeds the prompt twice.** `semantic_cache.py:468` embeds for lookup; `:710` embeds the *same string again* inside `store()`. Both go through `_embedding_gate = Semaphore(1)` (`:72`) and `Embedder._lock` (`embeddings.py:269, 274`), so all embedding in the process is serialised — a miss costs two serialised MiniLM inferences where one would do.

**7c. Every in-proc write throws away the tenant index.** `semantic_cache.py:760` `self._index.pop(tenant, None)` after a successful store. The next lookup calls `_build_index` (`:138`), which `SMEMBERS` the id set, pipelines `HGETALL` for every entry in batches of 64, and re-parses every CSV vector. With the default 256 entries per tenant that is a full rebuild after every single write. `_append` (`:172`) already exists and is unused on this path.

**7d. `ensure_index` runs on every RediSearch write.** `semantic_cache.py:743` → `redisearch_store.ensure_index` → `FT.CREATE` attempt (expected to raise `ResponseError`) + `FT.INFO` validation, per store. The lifespan already calls it once at startup (`main.py:130`).

**Consequence** Self-inflicted miss-path latency and a weaker cost story. The live run measured baseline p95 of 1,458 ms (`technical_applicability_live_20261101_v1/FINDINGS.md`). The project has already fixed the analogous sequential-shortlist problem (`redis_shortlist_benchmark.json`: 3.357 ms sequential → 0.896 ms pipelined), so this is the same class of fix.

**Smallest justified fix** Pass the lookup vector into `store()`; use `_append` instead of dropping the index; drop the per-write `ensure_index`; either extend singleflight to `chat_stream` or state the asymmetry in `docs/ARCHITECTURE.md`.

**Regression needed** Assert one embedding per miss; one `FT.INFO` per startup; an index-append test that does not re-read Redis; concurrent identical streaming misses → one provider call (if 7a is fixed).

---

### F8 — LOW-MEDIUM · confirmed implementation defect · LRU recency mixes the gateway clock and the Redis clock

**Where** `app/cache/storage.py:345` — `touch()` uses `score = time.time()` (gateway host). `app/cache/storage.py:66–67` — `_put_scoped` uses `redis_clock = await pipe.time()` (Redis server). Both write the **same** `{ns}:lru:{tenant}` and `{ns}:org:{org}:lru` sorted sets.

**Triggering scenario** Gateway container clock 5 s behind the Redis host. A hot entry served (touched) at gateway-time *T* gets score *T*; a cold entry written one second later gets Redis-time *T+6*. Under quota pressure `_put_scoped:174–188` evicts the lowest score first — i.e. the hot entry.

**Consequence** Wrong eviction order; hot shared answers evicted in favour of cold ones. Correctness of the data is unaffected.

**Confirmed evidence** The two clock sources in one ZSET. Not observable in the existing suite: `tests/test_scoped_capacity.py::test_served_hit_refreshes_scope_and_organization_lru` runs against fakeredis in-process, where both clocks are identical.

**Smallest justified fix** Use `pipe.time()` in `touch()` as well.

**Regression needed** A test that offsets the app's `time.time` relative to Redis `TIME` and asserts a touched entry survives eviction.

---

### F9 — LOW · confirmed implementation defect · legacy tenants always report zero evictions

**Where** `app/cache/storage.py:303–338` — the unscoped `put()` path deletes LRU victims (`:329–333`) but never increments `{ns}:evictions:{tenant}`, which only the scoped path writes (`:265–269`). `occupancy()` reads that key unconditionally (`:448`).

**Triggering scenario** A legacy API key (tenant `t_…`) exceeds `max_cache_entries_per_tenant`; entries are evicted; `GET /admin/cache/occupancy` still returns `"evictions": 0`.

**Consequence** The dashboard/occupancy view understates pressure for legacy keys. Observability only.

**Smallest justified fix** Increment and expire the eviction counter in the unscoped path too.

**Regression needed** Assert a non-zero eviction count after forcing LRU eviction on a legacy tenant.

---

### F10 — LOW · confirmed implementation defect · an explicit `workspace` scope request with no workspace is silently answered privately

**Where** `app/schemas.py:28–34` rejects `workspace` without `cache_scope="workspace"` but not the reverse. `app/organization.py:300–302`: `selected = workspace if requested == "workspace" else principal.default_workspace` → `None` → `ScopeDecision("private", "", "private_only", "no_default_workspace")`.

**Triggering scenario** `POST /v1/chat {"prompt": "...", "cache_scope": "workspace"}` with no `workspace` field, from a principal with two authorized workspaces and no application default. Expected: an error. Actual: HTTP 200, private scope, `scope_reason: "no_default_workspace"`.

**Consequence** A client that asked explicitly to share gets private behaviour and must read a secondary field to notice. Not a leak — the failure is in the safe direction.

**Smallest justified fix** Require `workspace` when `cache_scope == "workspace"` in `ChatRequest.one_input`, mirroring the existing reverse check.

**Regression needed** Assert 422/400 for that body shape.

---

### F11 — LOW · intentional design tradeoff worth stating out loud · privacy detection blocks ordinary technical sharing

**Where** `app/organization.py:26–31` `_PRIVATE_CONTEXT`.

**Triggering scenario** `"How do we rotate our internal service credential?"` matches `\b(?:my|mine|our)\s+(?:\w+\s+){0,3}(?:…|internal|…|credential)\b` → `content_eligibility` returns `private_only` → `scope_decision` returns private with reason `private_context` (`:309–310`) → the answer is written only to the asking employee's private scope, and a colleague asking the same thing gets a provider call. Any prompt containing an email address does the same.

**Consequence** Correct and conservative — and it directly limits the headline sharing feature. Choose demo prompts that avoid `my/our + internal/account/credential` and email addresses, and say why.

**Evidence** The code comments already say "this is not a comprehensive DLP system" and "Detection can only restrict an authorized shared write, never grant one" (`:70, 321`).

---

### F12 — LOW · confirmed compatibility boundary worth stating · provider profile and provider-secret digest are part of the workspace cache key

**Where** `app/organization.py:152–169` (`profile_compatibility` includes an HMAC of `os.environ[secret_env]`) and `:252–277` (that digest is hashed into the workspace tenant).

**Consequences** (both correct for answer compatibility, both surprising in a viva)
1. Two employees in the same workspace on **different** provider profiles never share answers, with no warning.
2. Rotating the provider API key changes `secret_digest`, changes the tenant, and orphans the entire workspace cache until TTL expiry.

**Smallest justified fix** None in code. Document both in `docs/ORG_WORKSPACE.md`.

---

### F13 — SUSPECTED, needs execution · the score transformation depends on an untested library contract

**Where** `app/cache/verifier.py:357–366` — `self.model.predict([...])` is assumed to return **raw** 3-class logits, over which the code applies its own softmax.

**Risk** With `sentence-transformers==6.1.0` pinned (hash-locked in `requirements.lock`), `CrossEncoder.predict` is expected to use an identity activation for a 3-label model. If a future bump applies softmax internally, the code softmaxes probabilities, compressing every score toward 1/3 — every `ACCEPT` would disappear and every candidate would become `REJECT`/`VERIFY`, **with no test failing**, because `tests/test_nli_input_bounds.py` supplies a fake model returning hand-written logits.

**Evidence** `PROJECT_PROGRESS.md` states the single-softmax contract was checked manually. No automated assertion exists. Label mapping itself is handled correctly (`:359–364` looks up `id2label` for a label containing `entail` and raises if absent).

**Regression needed** One offline test against the pinned local model asserting an identical question/answer pair scores above `accept_at` and a flatly contradictory pair scores below `reject_below`. This converts a manual check into a guard rail.

---

### F14 — SUSPECTED, needs execution · the streaming upstream is opened before the response is returned

**Where** `app/main.py:948–958` calls `registry.route_events` (which consumes the first token and holds a circuit-breaker lease) before `StreamingResponse` is constructed at `:1104`.

**Risk** If the client disconnects before consuming the body, `event_gen` never runs, so the `finally` in `registry._wrapped` (`providers/registry.py:219–220`) never calls `gen.aclose()` and `breaker.record_success/failure` is never called. The breaker `probe` key stays set until its TTL (`breaker.py:184`), which can suppress that provider for other requests, and the httpx stream is held.

**Mitigation already present** The probe key has a finite expiry, so this self-heals.

**Regression needed** A client-disconnect test on `/v1/chat/stream` asserting the upstream generator is closed and no breaker lease is left held.

---

---

### Uncommitted dashboard work — reviewed separately (re-check, 2026-11-01)

`HEAD` is still `37dc7a7`. The tree additionally carries uncommitted changes to `app/static/dashboard.html` (+34/−21), `tests/test_dashboard_private_chip.py` (+33/−?) and `docs/ORG_WORKSPACE.md`. Reviewed as a separate, unfinished implementation; the verdict below replaces the three dashboard rows in §4.

**This change is a net improvement and it closes a real honesty gap.** Specifically:

1. **The hidden scope override is gone.** Previously the "private isolation" chip passed `options:{cache_scope:"private"}` into `ask()`, which applied it via `Object.assign(payload, exampleOptions)` **whenever a development demo was available, regardless of the override panel being open**. The dashboard therefore sent a scope the operator had not chosen and could not see. That chip, the `exampleOptions` parameter and the `Object.assign` are all removed; `grep` confirms no leftover references.
2. **The override panel is now double-gated**: `hidden = !(developmentDemoAvailable && new URLSearchParams(location.search).get("developer")==="1")`, so manual scope selection requires both a development demo *and* an explicit `/ui?developer=1`. `ask()` now predicates on `!$("dev-overrides").hidden && .open`, so a hidden panel cannot contribute a field. If `health()` fails, the `hidden` attribute present in the markup keeps the panel closed — the default is safe.
3. **Explanation consistency improved.** A new `storage scope / explanation` field renders `(storage_scope || "not stored") · (storage_reason || scope_reason || …)`, and `actual lookup scope` now reads `lookup_scope` before `cache_scope`. Both match what `main.py` actually returns.
4. **The test now verifies a stronger property than the one it replaced.** It asserts exact dict equality — `observed[-1] == {"prompt": "…"}` — so a normal request cannot smuggle *any* extra field, then separately asserts the `?developer=1` path sends `{"prompt": …, "cache_scope": "private"}`. I traced the fixture: the directory is written to `tmp_path/"organizations-demo.json"` and `settings_for` sets `api_keys=""`, `llm_provider="mock"`, development environment — so `organization_demo_available` is true, `ORG_EX` renders, and the `count() == 2` and `#rscope == "workspace"` assertions follow correctly from `content_eligibility("Explain how Python decorators work.") == "shared_eligible"` plus the injected `application_defaults`. The assertions are sound.
5. **The documentation was updated consistently**, and the replacement demo step is *better* product evidence than the one it replaces. `docs/ORG_WORKSPACE.md` now says to ask `Explain my Redis password` and relies on **server-side** classification instead of a client override. Verified against the code: `_PRIVATE_CONTEXT` matches `my` + `Redis` + `password` → `private_only`; `_ACTUAL_SECRET` does **not** match (no `:`/`=` after `password`), so it is not `no_store`; `scope_decision` therefore returns `("private", "", "private_only", "private_context")` with no client field at all. The claim is correct.
6. **`DEMO_ANSWERS` already covers the org fixture** (`dashboard.html:364` includes the Python decorator answer), so a HIT on the seeded org fixture is still labelled "matches seeded fixture" rather than being confused with a mock placeholder. Promoting `answer source` to top level strengthens this.
7. HTML is well-formed: `div` 105/105, `details` 2/2, `summary` 2/2, `section` 4/4.

One new finding follows.

---

### F15 — MEDIUM · confirmed · the newly promoted "total gateway time" excludes authentication, admission and body handling

**Where** uncommitted `app/static/dashboard.html:289` — the field `<span>total gateway time</span><b id="rlat">` — populated at `:423` from `d.latency_ms`, which `app/main.py:756` and `:880` compute as `time.perf_counter() - t0`.

**Triggering scenario** Any dashboard request. The displayed "total gateway time" is measured from `t0`, which `main.py` sets **after** `_auth`, `_principal`, `_registry_for`, `_admission_identity` and `await _check_rate_limit`. It therefore excludes:
- credential resolution — two `OrganizationDirectory.resolve` calls, each doing a `Path.stat()` and an HMAC comparison against every configured credential;
- the rate limiter's Redis round-trip (`rate_limit.py:allow`);
- provider-registry selection;
- everything in the two ASGI middlewares — concurrency admission, request-body buffering up to `max_request_bytes` with its own `request_body_timeout`, and logging.

**Consequence** The number a viva audience reads as the gateway's total cost is a sub-span of the request, and the change **demoted the one displayed number that does cover the whole request** — `browser HTTP time` (`rhttp`) — into the collapsed section. Before the change both sat side by side and the label was the accurate "gateway time". This is the "latency claims include all relevant stages" concern in area G, introduced by a label.

**Confirmed evidence** `t0` placement verified by extracting `chat()`: `_auth` → `_principal` → `_check_rate_limit` all precede `t0 = time.perf_counter()`. The project's own Prometheus histograms are honest about this — `CLIENT_TTFB` and `CLIENT_COMPLETE` are observed in `limits.py:33, 35` from the top of the middleware stack, i.e. they *do* measure the full span. Only the dashboard label overstates.

**Smallest justified fix** Rename the field to `gateway time (after auth)` — or keep `total` and move `browser HTTP time` back out of the collapsed block beside it. One word, no logic change.

**Regression needed** None beyond the existing browser test; if the label is kept, add an assertion that `browser HTTP time` is visible without expanding the details.

**Presentation note (not a defect)** The justification for a reuse decision — `candidate decisions`, `NLI model evidence`, `reason` — is now collapsed by default while speed and `answer source` are promoted. This inverts the emphasis for a product whose claim is *justified* reuse. It is substantially mitigated by `rbadge` staying at top level, since it renders the decision itself (`ACCEPT · HIT`, `VERIFY · MISS`, `DECLINED · MISS`). Consider expanding the details by default during the demo.

---

### F16 — HIGH · confirmed · `CACHE_MATCH_MODE=semantic` without the policy artifact is a measured reject-all for paraphrases

**Where** `app/cache/semantic_cache.py:77–83` builds the default `CachePolicy(use_adaptive=True, use_verifier=True, use_nli=False)`; `_lookup`'s `elif not exact:` branch at `:617–620` calls `self._policy.decide` whenever `self._answer_policy is None`, i.e. whenever `ANSWER_POLICY_ARTIFACT` is unset — which `app/config.py:58` describes as "empty keeps historical semantic policy".

**Triggering scenario** Set `CACHE_MATCH_MODE=semantic` and leave the artifact line commented out — **exactly how `.env.example:16–18` ships**, where the artifact sits under a commented "For local research only" heading. Then ask "how do I reset my password", then "what is the process to recover my account password".

**Execution path** Retrieval succeeds and similarity clears the adaptive threshold, then `policy.decide:49–58` → `verify_equivalent` → `_token_diff_reason` (`verifier.py:235–248`), which rejects on any changed token that is not a pure function word → `verify_rejected:content_token_mismatch` → MISS → provider call. Lexical paraphrase *is* the positive class, so essentially nothing survives.

**Consequence** That configuration serves only exact-prompt matches; the semantic path never accepts. Someone setting up the demo by flipping one documented variable gets a cache that looks broken, and the dashboard will show `semantic` mode with a long run of MISSes.

**Confirmed evidence** This is the project's own committed measurement, not my inference. `evaluation/results/metrics.csv` and the generated `report/generated/ablation.tex` record, for 15 positive + 15 negative pairs:

| System | Positive recall | Negative acceptance | Accepted | true/false accepts |
|---|---:|---:|---:|---|
| Baseline (static T=0.72) | 40.0% | 46.7% | 13 | 6 / 7 |
| + Adaptive T | 33.3% | 33.3% | 10 | 5 / 5 |
| + Verifier (Tier-1) | **0.0%** | 0.0% | **0** | 0 / 0 |
| VeriGate (Tier-1) — `run.py:218` calls this "recommended default config" | **0.0%** | 0.0% | **0** | 0 / 0 |

`verifier.py:11–12` already warns that "the token-diff check is conservative: it can reject valid paraphrases"; the measurement shows it rejects all of them on this fixture.

**Uncertainty** The fixture is 30 hand-authored pairs (F17), so "0 of 30" is not an error rate. The qualitative conclusion — token-diff rejects lexical paraphrase, which is the only thing semantic retrieval is for — follows from the rule itself, not the sample.

**Smallest justified fix** No code change is needed for the demonstration: always set `ANSWER_POLICY_ARTIFACT`. For the trap itself, either (a) have `lifespan` log a startup warning when `cache_match_mode == "semantic"` and no artifact is configured, stating that the historical Tier-1 policy rejects most paraphrases, or (b) say so in `.env.example` next to the mode. Do not change `_token_diff_reason` to make the table look better — that would be tuning on an inspected fixture.

**Regression needed** A test asserting that semantic mode with no artifact returns MISS with a `verify_rejected:` reason for a known paraphrase, pinning this as intentional conservatism rather than an accident.

---

### F17 — MEDIUM · confirmed evaluation weakness · the CI accuracy gate scores a 30-pair hand fixture and a 4-case volatility control set

**Where** `evaluation/run.py` — the module CI runs as its "Run evaluation (accuracy)" step and the source of `metrics.csv`, `tradeoff.png` and `ablation.png`.

**What it actually measures**
- `evaluate:72–79` scores **only** `benchmark.POSITIVES` (15 pairs) and `benchmark.NEGATIVES` (15 pairs, grouped 5 entity-swap / 3 number-swap / 2 negation / 5 related-topic). `evaluation/datasets.py:40` says of this same fixture: *"The historical hand fixture; never use it as an independent test set."*
- `_compute_sweep_curves:197` sweeps 21 thresholds from 0.45 to 0.95 **over those same 30 pairs**, so the trade-off curve that `run.py` calls "the money graph" and that chapter 6 reproduces as `tradeoff.png` is in-sample.
- `evaluate_volatility:90` measures false positives against `benchmark.STABLE_CONTROLS`, which is **four** queries — "what is the capital of France", "how do I reset my password", "who wrote Romeo and Juliet", "how do I install python". I checked: none contains any volatility keyword, so the gate reports 0/4 by construction. The project's own later dev set reports 6/12 on a **disjoint** set (zero overlap between the two stable sets). The CI number therefore cannot detect F3.

**Consequence** The only accuracy number CI enforces on every push is computed on a development fixture the codebase itself forbids using as a test set, with an in-sample threshold sweep and a volatility control set too small and too easy to fail.

**Not misleading documentation.** The committed `report/chapters/6_Results.tex:28–32` states plainly that the fixture is small, was used during development, that "thresholds and heuristic weights were not selected on a separate validation split", and that the differences "cannot establish generalisation or a fair comparison with published systems". It also correctly notes the experiment supplies a designated stored query with zero density and so "tests a decision rule in isolation, not candidate retrieval". The generated table's caption repeats the denominator caveat. The weakness is real; the write-up is honest about it.

**The gap in the write-up** Chapter 6 \inputs the table and then discusses "the displayed differences" without stating the most visible fact in it: two of the four rows, including the one `run.py` labels the recommended default, accept **nothing**. That is the first question an examiner will ask.

**Smallest justified fix** Point `evaluate_volatility` at `evaluation/dev/freshness_cases_v1.tsv` (12 stable / 12 volatile) instead of the 4 controls, or print both sets side by side; and add two sentences to chapter 6 stating that the Tier-1 rows are reject-all on this fixture and why (F16). Neither touches a threshold.

**Regression needed** Assert in CI that the volatility gate runs against the dev TSV and that `stable_bypassed` does not regress.

---

### F18 — MEDIUM · confirmed · per-candidate verification can cost as much as the provider call it avoids

**Where** `app/cache/semantic_cache.py:534–612` — the candidate loop — against `app/config.py:75–76` (`semantic_verify_limit = 5`, `semantic_verify_budget_ms = 1500`).

**Measured per-candidate cost** The committed `evaluation/results/latency.csv` / `report/generated/latency.tex` record `tier2_nli` at **p50 365 ms, p95 883 ms, p99 1762 ms**, against `hit_tier1_n1000` p50 30 ms and `embed` p50 46.5 ms. The technical lockbox measured the same model much faster on its short answers — **84.6 ms median, 101.8 ms p95** per verifier call (`technical_bidirectional_lockbox_20261101_v1/results_timed/summary.json` and the per-row `verifier_ms`). So the realistic per-candidate range is roughly **85–365 ms at p50**, depending on input length and machine.

**The loop does not stop on success.** `_lookup` iterates `candidates[:limit]` and on `ACCEPT` appends to `accepted` and **continues** — there is no `break` — because the `for…else` needs every decision to test `conflicting_accepted_answers` (`:613–620`). One lookup therefore pays up to 5 × per-candidate cost even when rank 1 already accepted.

**Pathological case** The budget caps the spend at 1500 ms, after which `reason = "verification_budget_exhausted"` → MISS → **the provider is called anyway**. The request pays the full verification budget *and* the generation. Observed in the live run: `technical_applicability_live_20261101_v1/FINDINGS.md` records one baseline request reaching `verification_budget_exhausted` and a baseline subsequent p95 of 1458 ms against a median of 342 ms.

**On the "speedup" number** `evaluation/latency.py:49` hardcodes `LLM_REFERENCE_MS = 800.0` ("a typical hosted-LLM end-to-end latency") and `_measure_speedups:123–141` prints "Nx faster than 800ms LLM call". **This never reaches the CSV or the report** — `latency.tex` carries only stage timings under the caption "these are not end-to-end provider latency", which is correct. But that stdout line is the only speedup figure the project produces, it is built on a literal rather than a measurement, and it is easy to copy into a slide. Treat it as unusable.

**Consequence** The cost argument for verification is not established and may invert: at 5 candidates and the upper end of the measured per-candidate range, verification alone approaches or exceeds the assumed provider latency, and the budget-exhausted path pays both.

**Smallest justified fix** Break out of the loop once a candidate accepts and no higher-ranked candidate produced a conflicting accept — the conflict check only needs the accepted set, which can be decided incrementally. Keep the budget and conflict semantics identical. Then re-measure.

**Regression needed** Assert that a rank-1 ACCEPT performs exactly one verifier call when no other candidate has already accepted, and that the existing `conflicting_accepted_answers` and budget tests still pass unchanged.

---

### F19 — LOW-MEDIUM · confirmed in uncommitted work · `latency_ms` and `stage_latency_ms` mean different spans on the two endpoints

**Context** An uncommitted change to `app/main.py` (+32 lines, appeared during this pass) adds the JSON response's decision fields to both streaming `event: meta` frames — identity, provider profile, candidate trace, ranks, candidate count, threshold, similarity, top retrieved similarity, NLI score, `verifier_invoked`, `latency_ms` and `stage_latency_ms`. **This is a good change**: it closes a real JSON/streaming explanation-parity gap, so a streaming client can now justify a served answer exactly as a JSON client can.

**The defect it exposes** The two endpoints compute the same two field names over different spans:
- `chat_stream` sets `started = time.perf_counter()` as its **first statement**, before `_auth`, `_principal`, `_registry_for`, `_admission_identity` and `await _check_rate_limit`. Its `latency_ms` therefore **includes** authentication, two directory `stat()`+HMAC resolutions and the rate limiter's Redis round-trip.
- `chat` sets `t0` **after** all of those. Its `latency_ms` **excludes** them (this is the F15 mechanism).
- `chat_stream` has no `stage_ms` dict at all (zero occurrences), so its `stage_latency_ms` carries only the lookup stages from `LookupResult`, whereas `chat` emits `{**result.stage_latency_ms, **stage_ms}` including `admission`, `provider` and `cache_write`.

**Triggering scenario** Compare `/v1/chat` and `/v1/chat/stream` on the same prompt and read `latency_ms` from each, or chart them together. The streaming figure is systematically larger by the auth-plus-admission cost, and its `stage_latency_ms` is missing the provider and cache-write stages, so the stages no longer sum toward the total.

**Consequence** Any JSON-versus-streaming latency comparison compares unlike quantities, and the streaming stage breakdown cannot be reconciled against its own total. Both are newly visible to clients.

**Smallest justified fix** Move `t0` in `chat` to the top of the function so both endpoints measure the same span — that also fixes F15's label honestly — and give `chat_stream` a `stage_ms` dict covering admission, provider and cache write, merged into the meta frame the way `chat` already does.

**Regression needed** One test asserting that, for the same prompt, both endpoints' `latency_ms` cover the same span (e.g. both exceed a deliberately slowed rate limiter) and that the streaming `stage_latency_ms` contains the provider and cache-write keys on a miss.

---

### F20 — MEDIUM · confirmed evaluation weakness · a paired design is analyzed with unpaired intervals, and the headline intervals overlap

**Where** `scripts/analyze_stress_semantic_http.py:116–141` (`family_interval`) and the `aggregate.csv` columns it produces.

**What it does right** It bootstraps over `family_id` groups rather than over individual requests, so the interval reflects clustering across the 200 songs instead of treating 1,000 correlated rows as independent. That is the correct unit, and `REPORT.md` says so: the intervals "measure sampling variability across these 200 authored families, not uncertainty from incomplete NQ answers or production traffic."

**The defect** Each policy arm is bootstrapped **separately**, producing two marginal intervals that are then compared by eye. From `nq_song_stress_20261030_v3/aggregate.csv`, suspected-wrong-per-request:

- static threshold: **(0.062, 0.123)**
- answer-aware: **(0.032, 0.076)**

Those intervals **overlap** on [0.062, 0.076]. So as reported, the improvement from 90 to 54 suspected wrong hits is not clearly separable from sampling variation.

**Why that is avoidable** Both arms run the *same* 200 frozen families, in the same frozen order, against the same provider answer map — a fully paired design. A per-family paired-difference bootstrap (static minus answer-aware, family by family) removes the between-family variance that dominates both marginal intervals and would very likely show a clearly positive effect. The analyzer already groups by family, so the machinery is in place.

**Consequence** The strongest claim available from the project's largest evaluation is currently reported in its weakest statistical form. A viva examiner who notices the overlap can argue the headline improvement is unestablished — when a paired analysis of the same data would probably settle it.

**Smallest justified fix** Add a paired per-family difference bootstrap for `suspected_incorrect_hits` and `correct_hits` between the static and answer-aware arms, and report that interval next to the two marginal ones. No label, threshold, or workload change.

**Regression needed** Assert the paired interval is computed over an identical family set in both arms and that it is reported whenever both arms are present.

---

### F21 — framing finding, not a defect · the measured trade-off is that verification costs reuse *and* provider calls to reduce suspected wrong answers

**Evidence** `evaluation/runs/nq_song_stress_20261030_v3/aggregate.csv`, sufficient capacity, 1,000 requests, same frozen workload and provider map for all three arms:

| Policy | Correct hits | Suspected wrong | Provider calls | Warm HTTP p50 | Verifier calls |
|---|---:|---:|---:|---:|---:|
| exact | 0 | 0 | 1000 | 35.2 ms | 0 |
| static threshold | 712 | 90 | 198 | 63.9 ms | 0 |
| answer-aware | 682 | 54 | 264 | 211.6 ms | 917 |

Read against the static threshold, the answer-aware policy is **−30 correct hits, −36 suspected wrong hits, +66 provider calls (+33%), and +148 ms at p50 (3.3×)**. Read against no semantic cache, both semantic arms remove roughly 74–80% of provider calls.

**Why this matters** It answers the brief's question — "whether measured provider-call savings justify verification overhead" — and the answer is specific: **the savings come from semantic matching, not from verification.** Verification is a net cost in calls, reuse and latency, bought in exchange for fewer suspected wrong answers. That is a perfectly defensible engineering position for a cache that must not serve wrong answers, but it is the opposite of "the answer-aware policy improves the cache", and the report must not imply the latter.

**Already honest in the repo** `REPORT.md` for this run states the counts, notes the verifier false rejections as "lost reuse against the authored references", and adds "these observations do not establish real-answer correctness." The framing above is a sharpening, not a correction.

**What to do** State the trade-off in exactly these terms in the report and the viva, with all three arms and both denominators. Do not quote the 90→54 reduction without the +66 provider calls and +148 ms beside it, and note F20's interval overlap.

---

### F22 — LOW · confirmed evaluation gap · the deployment-capacity arm does not stress the semantic policies

**Where** `scripts/stress_semantic_http.py:184–187` — the two capacity settings: `sufficient` = TTL 86,400 s / 1,200 entries, `deployment` = TTL 3,600 s / 256 entries.

**Observation** In `aggregate.csv` the `static` and `answer_aware` rows are **byte-identical** between the two capacities in every outcome column (712/90/198/183 and 682/54/264/249 respectively). Only the `exact` arm changes: reuse opportunities 788 → 599 and `expiry_or_eviction_misses` 0 → 189.

**Explanation (verified, not a bug)** The semantic policies write only on a miss. `cache_write_stage_n` is **183** for static and **249** for answer-aware — both below the 256-entry deployment cap — so no eviction can occur. The `exact` arm writes 985 entries and therefore does hit the cap. The identical rows are a consequence of the cap never binding, not evidence of robustness under pressure.

**Consequence** The "deployment capacity" dimension contributes no information about the semantic policies, which are the ones under test. Quoting it as evidence that the semantic cache behaves correctly under production-like limits would be unsupported.

**Smallest justified fix** Either set the deployment cap below the observed write count for the semantic arms (e.g. 128) or increase the number of distinct questions, and record the cap next to the actual write count in `aggregate.csv` so the arm's reach is explicit.

**Regression needed** Assert that at least one semantic arm records a nonzero `expiry_or_eviction_misses` under the deployment capacity, otherwise flag the arm as non-binding in the report.

---

### Evaluation weaknesses (section F of the brief)

| # | Weakness | Evidence |
|---|---|---|
| EW1 | Every technical workload's cached answers are 61–99 characters, so the realistic long-answer path — the one F2 shows is unverifiable — is never exercised on the live path. | computed from `technical_applicability_live_20261101_v1/workload.json` |
| EW2 | Live-run provider answers are a constant placeholder per family, so these runs measure reuse **decisions** only, never answer quality. Correctly stated in the docs, but it means "no incorrect accepts" is about applicability, not truth. | `scripts/evaluate_live_combined.py:57–61` |
| EW3 | Denominators are 15 valid / 5 invalid / 5 ambiguous per variant. No confidence intervals are reported for any technical run, although `evaluation/protocol.py:bootstrap_ci` exists and is used elsewhere. 0/5 invalid accepts is compatible with a true rate above 0.5. | run `summary.json` files; `evaluation/protocol.py:62` |
| EW4 | Technical labels are authored stipulations by the implementer. `evaluation/datasets.py:113 reviewed_answers()` enforces two distinct reviewers and `resolved_two_reviewers` status — no technical set meets that bar, and only 75 development pairs exist. | `PROJECT_PROGRESS.md`; `datasets.py:140–147` |
| EW5 | Warm-latency comparisons drop only the first request and compare two separate processes whose decision paths differ in length; the OFF variant runs more NLI calls by construction. The docs already decline to claim a repeatable speedup. | `evaluate_live_combined.py:_summary`; `technical_applicability_live_20261101_v1/FINDINGS.md` |
| EW6 | Volatility, the one sub-contribution with a labelled dev set, is validated only on finance/physics phrasing; its technical behaviour is unmeasured (F3). | `evaluation/dev/freshness_cases_v1.tsv` |
| EW10 | **The 1,000-question stress denominator is not 1,000 independent observations, and the dominant uncertainty is not the one the intervals cover.** The positive class is exactly **three authored paraphrase templates** — "Name the writer of the song X.", "For the song X, who is credited as its writer?", "Identify the person who wrote the song X." — instantiated 200 times each, plus the source wording and one entity-swap negative (`stress_semantic_http.py:96–124`). The family bootstrap resamples songs, so the intervals answer "what if we drew different songs?" and not "what if we drew different ways of asking?", where n = 3. `by_category.csv` shows the templates differ materially: answer-aware reuse-per-opportunity 0.9355 / 0.9257 / **0.8784** / 0.9388 and verifier false rejections 10 / 11 / **18** / 9 across original and the three paraphrases — the fronted "For the song…" form is consistently worst. Template choice therefore moves the result more than song choice, and that variance is outside every reported interval. The run's own `REPORT.md` does state that all three forms produced both reuse and suspected wrong reuse, and publishes the per-template table. | `scripts/stress_semantic_http.py:96–124`; `nq_song_stress_20261030_v3/by_category.csv` |
| EW11 | Positive: **the stress outcome taxonomy is grounded in live cache state and anticipates the obvious metric trap.** `stress_semantic_http.py:233–244` (`live_entries`) reads this evaluation tenant's actual Redis entries immediately before each request, so "unnecessary miss" means a suitable answer genuinely was resident. `classify:212–230` decides a hit by comparing the **served answer** to that row's own `reference_answer`, not to the row's `kind` — so a hard negative that legitimately reuses the neighbouring family's correct entry is scored `correct_hit`, not a false accept, and the analyzer says so explicitly ("Hard negatives can legitimately reuse a different family's cached answer"). `verifier_false_rejection` additionally requires the *selected* candidate's answer to equal the reference. Two denominators are published: a frozen-order "common potential reuse" of 800 and per-arm live opportunities. | `scripts/stress_semantic_http.py:212–244`; `analyze_stress_semantic_http.py` |
| EW12 | Positive: mining and reporting hygiene. `build_answer_pairs.py` caps negative-question reuse at two (`MAX_NEGATIVE_QUERY_USES = 2`), enforces group sizes 2–4, entity-span swaps and a content-Jaccard floor, and emits both the alias proxy and the stricter concrete-answer label — with matching tests in `test_gold_answers.py`. `summarize_experiments.py` generates `docs/RESULTS_EXPERIMENTAL.md` directly from the result CSVs and propagates `*_ci_low`/`*_ci_high` columns, so those document numbers are not hand-typed. | `scripts/build_answer_pairs.py:35–51`; `scripts/summarize_experiments.py:26–47` |
| EW8 | Gold-label provenance for the NQ study is a **string proxy**, and its error rate is partly quantified: `reuse_ok` is a symmetric alias-set intersection (`gold_answers.py:48–52`, "not a specific-answer reuse label"), and `evaluation/results/answer_label_audit.json` records 124 of 6,000 historical positive rows where the cached answer text is absent from the incoming question's aliases, with `review_status: "unreviewed"` and `label_meaning: "reference-string membership only; actual reuse needs human review"`. The loader does enforce internal consistency, raising if a label disagrees with its aliases or if one question carries inconsistent aliases (`gold_answers.py:149–155`). | `evaluation/gold_answers.py`; `answer_label_audit.json` |
| EW9 | Positive: the `verify_*` CI gates are real integrity checks, not smoke tests. `scripts/verify_live_combined.py` re-hashes the workload against `freeze.json`, re-hashes **the evaluator source and the policy artifact** against the run manifest, asserts the row order and labels match the frozen workload exactly, re-derives every summary count from the raw rows, and asserts the readiness snapshot proves the intended variant was running. Post-hoc editing of a summary number, a changed workload, a changed artifact or a changed evaluator would all fail CI. The one excluded first run (`results/`, documented as having used a different evaluator source) is correctly outside both the gate and the claims. | `scripts/verify_live_combined.py`; `.github/workflows/ci.yml` |
| EW7 | Positive: the structural anti-leakage work is genuinely sound — union-find over queries *and* families across a 4-way split, SHA-256 workload freezes, pre-registered labels, five CI validators, and `test_evaluation_integrity.py` asserting that a reject-all policy is not reported as perfect precision. | `datasets.py:174–214`; `.github/workflows/ci.yml` |

---

## 4. Product-claim table

Status is against the committed baseline `37dc7a7`. The three dashboard rows are additionally re-verified against the uncommitted dashboard change (see "Uncommitted dashboard work" after F14); each still holds, with the one caveat in F15.

| Claim (from the product goal) | Status | Code / evidence |
|---|---|---|
| Authenticate the caller with a VeriGate credential | **Implemented** | `organization.py:217–241`, `identity.py:20–29`, `main.py:170–186`; digest-only storage, constant-time comparison across all keys |
| Resolve employee identity, workspace permissions, cache scope, provider profile | **Implemented** | `organization.py:285–317`, `:252–277`; `main.py:203–245`; `test_organization_scopes.py` (19 tests) |
| Credential revocation takes effect, including mid-request | **Implemented** | `main.py:214–220, 750, 824`; `test_revocation_during_hit_lookup_prevents_serve`, `test_revocation_after_generation_prevents_shared_write` |
| Cross-organization / cross-workspace / private isolation | **Implemented** | scope built into the HMAC tenant; `redisearch_store.knn:150–197` re-validates the tenant tag per row; `test_shared_private_cross_org_and_forged_scope` |
| Authorized employees share reusable technical answers in their workspace | **Implemented, with two boundaries** | works for same-profile members (`config/organizations-demo.json`); silently does not for different provider profiles or after a provider-key rotation (F12); blocked by privacy detection for `my/our + internal/credential` prompts and any email (F11) |
| Server-configured provider profile, secrets never in config | **Implemented** | `organization.py:131–151` rejects `api_key`/`secret` keys and requires an env reference; `profile_secret:243–250`; `registry.from_profile` |
| Retrieve eligible candidates with embeddings and Redis vector search | **Implemented** | `semantic_cache._ranked:234–291`; `redisearch_store.ensure_index/knn`; HNSW + COSINE + tenant TAG, schema validated at startup and readiness |
| Top-k ordering, later-candidate handling, entry-identity checks | **Implemented** | `_ranked` deterministic tie-break; `_lookup:645–681` re-reads and compares the selected hash before serving; `:559–567` reports a later abstention instead of the rank-one rejection |
| Decide whether a candidate answer can appropriately answer the request | **Partial — the central gap** | implemented (`answer_policy.decide`) but measured at 4/15–8/15 valid reuse with 3/10 ambiguous accepts in the shipped configuration (F1); unverifiable above ~900 characters of answer (F2) |
| Serve a *justified* cached answer | **Implemented** | per-candidate `candidate_trace` (rank, similarity, action, reason, verifier status, NLI score, elapsed ms) in JSON and SSE `meta`; rendered in the dashboard with separate selected and explanation ranks. In the uncommitted change the trace, NLI score and reason move into a collapsed "How this request was handled" block — still rendered, but one click away; the decision badge stays top-level |
| Fall back to the provider on VERIFY/REJECT | **Implemented** | `VERIFY` and `REJECT` both yield MISS → provider; `_count_candidate_decision` meters each action |
| Store eligible completed responses with correct scope, retention, limits | **Implemented** | explicit terminal event required (`main.py:435–443`); `private_only` responses downgraded to the private scope with origin metadata (`:779–792`); per-scope and per-organization entry/byte quotas with atomic `WATCH` transactions and Redis-clock expiry reconciliation (`storage.py:47–289`) |
| Partial or failed generations never cached | **Implemented** | `test_partial_stream_never_caches`, `test_empty_provider_answer_is_not_cached`, `test_length_filtered_and_missing_finish_are_never_cached` |
| Cache-write failure preserves the provider answer | **Implemented** | `_cache_store` returns an outcome string, never raises; `test_cache_write_failure_preserves_generated_json_answer` |
| Exact matching as an internal optimization | **Implemented** | `_lookup:426–464` serves an identical question without embedding or NLI, with a touch-then-reread identity check |
| Time-sensitive queries bypass the cache | **Partial / defective** | all 12 volatile dev cases bypass, but 6 of 12 stable cases also bypass (F3); unvalidated on technical phrasing |
| Adaptive per-query similarity threshold (sub-contribution A) | **Partial — mutually exclusive with the answer policy** | `threshold.adaptive_threshold` runs only in the `elif not exact` branch (`semantic_cache.py:617–621`). With `ANSWER_POLICY_ARTIFACT` set, the threshold is the artifact's fixed `min_similarity` (0.35) and the adaptive logic never executes |
| JSON / streaming explanation parity | **Partial at the baseline, improved in uncommitted work** | at `37dc7a7` the SSE `meta` frame carried scope, storage and usage but none of the decision fields; the uncommitted `main.py` change adds candidate trace, ranks, candidate count, similarity, threshold, NLI score, `verifier_invoked` and timings to both meta frames. F19 covers the span mismatch the addition exposes |
| Request coalescing / duplicate suppression | **Partial** | JSON only (`main.py:854`); the streaming endpoint has none (F7a); process-local, which the docs state |
| Circuit breaker, request budgets, deadlines, cancellation safety | **Implemented** | generation-checked shared breaker with an owned half-open lease (`breaker.py`); single request deadline threaded through every stage; `_infer` keeps gate capacity until the thread actually finishes (`test_cancelled_inference_retains_capacity`) |
| Redis outage behaviour and backend parity | **Implemented** | lookup failure → MISS with reason; admission failure → 503 fail-closed; `test_live_redis.py` covers both backends and two worker processes |
| Bounded verifier latency and memory | **Partial** | per-request verify budget and limit are enforced; memoization is bounded by entry count, not bytes (F6); all embedding and all NLI inference is serialised through two `Semaphore(1)` gates |
| Startup readiness and model prewarming | **Implemented** | prewarm is opt-in and gates readiness; `/ready` reports verifier state, failure category, policy version, active mode and guards; `test_policy_prewarm.py` |
| Demo fixtures distinguished from provider answers | **Implemented** | `demo_fixtures.demo_enabled` gates restoration behind seven simultaneous conditions; the dashboard labels "matches seeded fixture" / "mock placeholder" / "generated answer" and warns that a repeated MISS can hit a mock placeholder |
| No leakage through logs, traces, or UI | **Implemented** | logs carry `request_id`, hashed tenant, similarity, threshold — never prompts or answers (`logging_config.py`, `main.py:757`); `selected_cached_query` is exposed only under `llm_provider == "controlled-eval"` |
| Reproducible documented startup | **Implemented** | `scripts/start_org_demo.ps1` + `docs/ORG_WORKSPACE.md` give a complete PowerShell path with pinned models and public demo credentials; a shared semantic hit requires the documented explicit seeding step |
| Learned accept model / risk certification / task-reuse classifier | **Unsupported — scaffolding only, deliberately inactive** | `accept_model.py:76–80` refuses any artifact not labelled `reviewed_answer_reuse`; `risk.py` docstring states it is not enabled without reviewed labels; `reuse_verifier.py` requires a calibrated artifact that does not exist (`PROJECT_PROGRESS.md`: 75 pairs available, 600–4,000 needed) |
| Measured provider-cost savings | **Unsupported** | all runs use a mock or controlled provider; provider calls are counts, not cost. Stated as such in every `FINDINGS.md` |
| General semantic correctness / production accuracy | **Unsupported** | no human-reviewed labels, denominators of 5–15, no confidence intervals on technical runs |

---

## 5. Consolidated implementation prompt

> Preserve the existing product and architecture. Do not introduce new frameworks, change the scope/tenant key scheme, alter the storage schema, or move any threshold to fit a case that has already been inspected. Every behaviour change gets a regression test and a note in `PROJECT_PROGRESS.md`.

### A. Must fix before the demonstration

1. **Narrow the volatility gate (F3).** Two parts — part 2 is the one my first draft missed, and without it four of the twelve reproduced technical cases stay broken:
   1. In `app/cache/volatility.py`, make the volatile-*value* nouns (`price`, `prices`, `score`, `temperature`, `stock`, `stocks`, `current`, `news`) bypass only alongside a time reference or a possessive (`my`, `our`).
   2. Move `latest`, `live`, `recent`, and `up to date` out of `_EXPLICIT_TIME_RE:173–177` and subject them to the same co-occurrence requirement — each bypasses unconditionally today at `:190–191` and each has a common non-temporal technical sense (`latest commit`, `live reload`, `recent rows`, `up to date dependency`). Leave `today`, `now`, `right now`, `tomorrow`, `yesterday`, `tonight`, `this week/month/year`, and `as of` unconditional.

   Add ≥12 technical stable cases to `evaluation/dev/freshness_cases_v1.tsv` (Django `current` user, scikit-learn/PyTorch `score`, git `latest` commit, nginx `live` reload, Kafka `recent` rows, Renovate `up to date`, a `price` schema field, a systemd `temperature` threshold) and re-run `scripts/evaluate_freshness.py`. Acceptance: all 12 existing volatile cases still bypass; `stable_bypassed` drops below 6; no new technical stable case bypasses. Report both denominators.
2. **Make `too_long` visible and memoized (F2, F5a).** Put `input_tokens` into every `candidate_trace` row and into a `nli_input_tokens` histogram. Store the `too_long` assessment in the memo before returning (`verifier.py:355`). Then measure and record, in a new short run document, the cached-answer length at which the pinned model starts returning `too_long`. Do not change the formulation yet.
3. **Give the verifier a recovery path (F5b).** Replace `self.unavailable = True` with a consecutive-failure count plus a cooldown timestamp in both `verifier.py:367–371` and `reuse_verifier.py:143–147`. Keep fail-closed behaviour inside the cooldown and keep `last_failure_category` in `/ready`. Regression: one simulated transient load failure recovers after the cooldown; readiness returns to `ok`.
4. **Decide and document the demo configuration (F1).** Either run the demo with `ANSWER_POLICY_TECHNICAL_GUARD=true` and `ANSWER_POLICY_APPLICABILITY_GUARD=true` — the best measured trade-off (8/15 valid, 0/5 invalid, 0/5 ambiguous on a set frozen before the run) — or keep defaults. Whichever is chosen, record it in `QUICKSTART.md` and show it on the dashboard, state that the project's own promotion gate was not met, and give the exact denominators. Do not change the artifact.
5. **Pin the score-transformation contract (F13).** Add one offline test against the pinned local cross-encoder asserting an identical question/answer pair scores above `accept_at` and a flatly contradictory pair below `reject_below`, so a future `sentence-transformers` bump that double-applies softmax fails CI instead of silently disabling all acceptance.

6. **Fix the "total gateway time" label (F15).** In the uncommitted dashboard change, either rename the promoted field to `gateway time (after auth)` or move `browser HTTP time` back out of the collapsed block to sit beside it. One word or one line; no logic change. The measured number excludes authentication, directory resolution, the rate-limiter Redis round-trip and all middleware body handling, so the current label overstates it in the most visible place on the page. Consider also opening "How this request was handled" by default for the demo, so the justification is on screen next to the speed claim.

7. **Do not demo `CACHE_MATCH_MODE=semantic` without the artifact (F16).** It is a measured reject-all for paraphrases. Add a one-line startup warning when semantic mode is active with no `ANSWER_POLICY_ARTIFACT`, and note it in `.env.example` beside line 16 so the commented artifact is not read as optional decoration.
8. **Say what the ablation table shows (F17).** Add two sentences to `report/chapters/6_Results.tex` after `\input{generated/ablation}` stating that the two Tier-1 rows accept zero of thirty pairs because the token-diff rule rejects lexical paraphrase, and that this is why the answer-aware policy exists. The table is already in the report; leaving the 0.0% unexplained is the risk.

### B. Important follow-up

9. **Remove miss-path duplicate work (F7b–d).** Thread the lookup vector into `SemanticCache.store`; use the existing `_append` instead of `self._index.pop(tenant)`; drop the per-write `rs.ensure_index` (the lifespan already ensures it). Regressions: one embedding per miss; one `FT.INFO` per startup; an append path that does not re-read Redis. Re-run `scripts/benchmark_real_semantic.py` and report the miss-path p50/p95 before and after on the same runner.
10. **Narrow the structural recall killers (F4).** Restrict `_scope_terms` to question-head ordinals/superlatives or quantity-bound ones; restrict the yes/no-opener rejection to non-procedural cached answers. Freeze a new paraphrase set (superlative-vs-plain, polar-vs-procedural, ≥40 pairs) **before** changing the rules, and report valid-reuse and incorrect-accept counts separately on both sides. Update `test_changed_scope_abstains_without_nli` deliberately, with a comment saying why.
11. **Fix the LRU clock source (F8).** Use `pipe.time()` in `storage.touch`. Regression: offset the app clock against Redis `TIME` and assert a touched entry survives eviction.
12. **Stop verifying after an uncontested accept (F18).** Break out of the candidate loop once a candidate accepts and no higher-ranked candidate produced a conflicting accept, deciding `conflicting_accepted_answers` incrementally instead of after the full sweep. Keep the budget and conflict semantics identical, then re-measure the hit path. Also fix the volatility control set in `evaluation/run.py:90` to use the 12-case dev TSV (F17).
13. **Bound the verifier memo by bytes (F6).** Key on `sha256` digests of premise and hypothesis, or track summed bytes against a configured cap. Regression: memo byte footprint stays under the cap with large synthetic pairs.
14. **Report the paired difference on the stress comparison (F20).** Add a per-family paired-difference bootstrap between the static and answer-aware arms for `suspected_incorrect_hits` and `correct_hits`, and publish it beside the two marginal intervals, which currently overlap. The analyzer already groups by family. Also record the eviction cap next to the actual write count so the deployment-capacity arm's non-binding reach is explicit (F22).
15. **Close the small correctness gaps.** Reject `cache_scope="workspace"` with no `workspace` in `ChatRequest.one_input` (F10); increment the eviction counter in the unscoped `put` path (F9); add a client-disconnect test for `/v1/chat/stream` and close the upstream generator if it leaks (F14). Document the provider-profile and provider-secret-rotation cache boundaries in `docs/ORG_WORKSPACE.md` (F12) and the privacy-detection effect on sharing in the same file (F11).
16. **Either coalesce streaming misses or document the asymmetry (F7a).** If coalescing is added, the follower must receive the leader's buffered answer only when leader and follower resolve to the same tenant *and* the same `subject_id`, exactly as the JSON key already requires (`main.py:853`).

### C. Longer-term

17. **Replace the answer-assertion judge, under the protocol already written.** Follow `evaluation/runs/technical_applicability_live_20261101_v1/VALID_MISS_DIAGNOSIS.md` verbatim: fine-tune the already-pinned DeBERTa-v3-xsmall on `(cached question, cached answer, incoming question)` with grouped, independently reviewed technical labels from ≥3 disjoint sources; freeze a family-disjoint HTTP/top-k set with ≥150 valid, ≥150 invalid, 100 ambiguous probes; require ≥10 points of valid-reuse gain with no increase in incorrect accepts or ambiguous approvals, 95% binomial intervals, raw denominators, three order-balanced timing runs, warm p95 ≤ 2× the current model, RSS ≤ 1.2 GiB, and publish the artifact hash. Treat a failure as a negative result and keep the current default. The adapter, exporter, training pipeline and integrity checks already exist in `reuse_verifier.py` and `scripts/train_reuse_verifier.py`.
18. **Get two-reviewer technical labels.** `evaluation/datasets.py:reviewed_answers` already enforces `resolved_two_reviewers` with two distinct reviewers; nothing technical meets it. Until it does, no answer-quality claim is available at any sample size.
19. **Report intervals on technical runs.** `evaluation/protocol.py:bootstrap_ci` exists; wire it into `scripts/evaluate_live_combined.py` and the other technical summaries so every small-n number ships with its interval.
20. **Decide what "adaptive threshold" means.** Today the adaptive threshold and the answer policy are mutually exclusive branches (`semantic_cache.py:603–621`). Either compose them deliberately or retire sub-contribution A from the live path and describe it as an evaluated baseline.

---

## 6. Report-readiness guidance

### Safe to write now (verified against code and saved artifacts at `37dc7a7`)

- VeriGate is an organization-aware LLM gateway with HMAC-digest credentials, server-owned provider profiles, and cache scopes that bind organization, scope, subject, application, provider profile and route. No plaintext credential or provider secret is stored in configuration, keys, or logs.
- Cross-organization, cross-workspace, and cross-employee private isolation is enforced by key construction and re-validated per retrieved row; revocation takes effect immediately, including during an in-flight request and before a shared cache write.
- Authorized employees in the same workspace on the same provider profile do reuse each other's answers; prompts or answers matching the conservative privacy patterns are written only to the employee's private scope.
- Retrieval uses pinned MiniLM `all-MiniLM-L6-v2` (revision `1110a243…`) and a Redis Stack HNSW/COSINE index filtered by a tenant tag, with the vector schema validated at startup and on every readiness check.
- Candidate selection is deterministic, bounded by a retrieval limit, a verification limit and a verification budget, and ends in a re-read identity check so an entry replaced or expired mid-decision is not served. Every decision carries a per-candidate trace.
- A cached answer is served only on `ACCEPT`; `VERIFY` and `REJECT` both call the provider. Partial, empty, truncated, malformed and tool-call generations are never cached. Cache-write failure never loses the generated answer.
- On the frozen 25-probe, five-family technical workload (labels committed before the run, real MiniLM, Redis Stack, pinned NLI, controlled provider): all 15 suitable candidates were retrieved; **4 of 15** valid answers were reused with the shipping configuration; 0 of 5 invalid probes were accepted. The 11 valid misses were 5 `VERIFY` and 6 `REJECT` from the NLI decision, not retrieval failures.
- On the later frozen combined-guard run: baseline 6/15 valid and 1/5 ambiguous approvals; with both experimental guards on, 8/15 valid, 0/5 invalid, 0/5 ambiguous. The prespecified promotion gate required three more valid hits, so the guards remain off by default.
- On a disjoint 10-family lockbox, the shipping answer-assertion formulation reused 4/10 valid and accepted 3/10 deliberately underspecified requests; an experimental reverse-assertion check was worse (3/10 valid, same 3/10 ambiguous).
- The pinned NLI tokenizer's limit is **512 tokens**, measured directly from the model by `scripts/inspect_nli_window.py` and recorded in `evaluation/runs/nli_window_20261030_v2.json`. The same probe shows tokens per byte varying about 8× with content alone (499 bytes → 655 tokens for one input, 659 bytes → 335 tokens for another), so a byte or character count cannot stand in for the model's paired token length.
- Because the cached answer appears in both the premise and the hypothesis, it is charged twice against that window. One realistic 1,620-character / 244-word configuration procedure produced a 596-token pair and abstained with `context_too_long` on **all three** of its probes — valid, invalid, and underspecified — in both variants; the other nine answers in the same run were 175–252 characters and were all scored. This accounts for one of the six valid misses in that run.
- One NLI prewarm measurement: 30.6 s, +680.9 MB process RSS (includes Python/Torch runtime, not isolated model weights).
- A Redis shortlist microbenchmark: five sequential hash reads 3.357 ms median vs 0.896 ms pipelined, over 80 alternating rounds. This is a Redis-read measurement, not an HTTP latency claim.
- On the authored freshness set, all 12 volatile queries bypass and 6 of 12 stable queries also bypass — the volatility rules are keyword heuristics with a measured 50% false-bypass rate on that set. This reproduces exactly at the reviewed commit. A query caught by these rules is bypassed on read and refused on write, in exact as well as semantic mode.
- Evaluation method: SHA-256-frozen workloads, labels pre-registered before runs, union-find grouped 4-way splits over queries and families, explicit denominators, grouped bootstrap intervals in `evaluation/protocol.py`, and five CI validators that fail on any change to generated results. The validators are substantive: `scripts/verify_live_combined.py` re-hashes the workload against its freeze, re-hashes the evaluator source and the policy artifact against the run manifest, asserts the row order and labels match the frozen workload, re-derives every summary count from the raw rows, and asserts the readiness snapshot proves the intended variant was running.
- On the 30-pair hand-curated candidate-pair fixture, the static-threshold baseline accepts 13 of 30 pairs (40.0% positive recall, 46.7% negative acceptance), adaptive thresholding accepts 10 (33.3% / 33.3%), and both Tier-1 verifier configurations accept **zero** — the token-diff rule rejects lexical paraphrase, which is the positive class. This is a development fixture with an in-sample threshold sweep and no validation split; it cannot support a generalisation claim.
- Recorded stage timings (local, fakeredis, pinned models): embedding p50 46.5 ms, Tier-1 verification p50 0.03 ms, Tier-2 NLI p50 365 ms / p95 883 ms / p99 1762 ms, full Tier-1 hit path at 1,000 entries p50 30 ms, in-process KNN p50 0.05 ms at n=10 rising to 0.34 ms at n=2,000. On the technical lockbox the same NLI model measured 84.6 ms median / 101.8 ms p95 per call on short answers. These are stage timings, not end-to-end provider latency.
- The gold NQ labels are reference-string proxies, and the error is partly quantified: 124 of 6,000 historical positive rows have the cached answer absent from the incoming question's alias set, and the audit is marked unreviewed.
- On the frozen 1,000-request NQ-song workload (200 families × 5 variants, same order and provider map for every arm, sufficient capacity): exact matching served 0 hits and made 1,000 provider calls at 35.2 ms warm p50; the static threshold served 712 reference-matching hits with 90 suspected wrong and 198 provider calls at 63.9 ms; the answer-aware policy served 682 with 54 suspected wrong and 264 provider calls at 211.6 ms, invoking the verifier 917 times. Family-clustered 95% intervals: reuse per live opportunity (0.887, 0.951) and suspected wrong per request (0.032, 0.076) for answer-aware, against (1.0, 1.0) and (0.062, 0.123) for static.
- Stated as a trade-off: relative to the static threshold, verification costs 30 correct hits, 66 extra provider calls and about 148 ms at p50, and buys 36 fewer suspected wrong answers. The provider-call savings against no semantic cache come from semantic matching; verification is a net cost that buys a reduction in suspected wrong answers. The two suspected-wrong intervals overlap, so the reduction should be reported as suggestive unless a paired per-family analysis is added (F20).
- Outcome definitions for that workload are grounded in live cache state: the runner reads the evaluation tenant's actual Redis entries immediately before each request, scores a hit by comparing the served answer to that row's own reference answer, and counts a verifier false rejection only when the selected candidate's answer equalled the reference.
- The deployment default is exact-prompt matching; semantic mode, the answer-aware policy, the technical guard and the applicability guard are each separate opt-ins.

### Provisional — depends on the active implementation; re-verify before writing

- Any miss-path or warm-latency number: F7's duplicate embedding, index rebuild and per-write `ensure_index` are live in `37dc7a7`, and fixing them changes every miss-path timing.
- The applicable cached-answer length ceiling for the verifier. One measured point exists (1,620 characters → 596-token pair → `too_long`); the ~1,350–1,400-character break-even in this review is **extrapolated from that single point** and is content-dependent. Quote the measured point, not the extrapolation, until step A2 measures the curve — and do not state a ceiling in characters at all for code- or identifier-dense answers.
- Whether the demonstration runs with the experimental guards on, and therefore which reuse figure (4/15, 6/15 or 8/15) is the headline.
- Any revised volatility false-bypass count (currently 6/12).
- Any valid-reuse figure after the F4 scope-word and yes/no-opener work.
- Verifier memory figures if the memo is re-keyed (F6), and startup/readiness figures if prewarm behaviour changes (F5).
- Test counts: `PROJECT_PROGRESS.md` records 302 passed / 7 skipped locally and 308 / 1 skipped with Redis Stack on the working tree. Re-run and quote the number for the exact commit the report describes.
- Anything about the dashboard's layout, field labels, or the documented private-isolation demo step: all three are uncommitted and still moving. The current replacement step (`Explain my Redis password`, classified private by server policy) is verified correct against the code, but it is not yet committed.
- Any figure captioned as the gateway's total or end-to-end time taken from the dashboard: see F15. The `latency_ms` field, and therefore the dashboard's headline number, starts after authentication and rate limiting. If the report needs an end-to-end number, take it from the `verigate_client_complete_seconds` histogram, which is measured from the top of the middleware stack.

### Must not be claimed

- **Do not claim semantic or factual correctness of reused answers.** No human-reviewed answer labels exist; every technical label is an authored stipulation by the implementer, and `evaluation/datasets.py` has a two-reviewer gate that no technical set meets.
- **Do not claim cost savings in money or tokens.** Every run used a mock or controlled provider. Provider-call counts on 25 probes are not cost reductions. `daily_request_budget` counts admitted misses, not tokens or spend.
- **Do not present 0/5 invalid accepts or 0/5 ambiguous approvals as a safety guarantee.** With n = 5 the 95% one-sided upper bound is near 0.5. The run documents say this explicitly; the report must too.
- **Do not claim the gateway verifies answer correctness.** It estimates whether a stored answer is *applicable*; `answer_policy.py:1–5` and `verifier.py:18` say the NLI model judges compatibility of assertions, not truth.
- **Do not claim a latency improvement from the guards.** Two single sequential runs on one Windows machine with ~3 s of startup variance; the project's own `FINDINGS.md` declines this claim.
- **Do not claim the learned accept model, the conformal risk guarantee, or the task-reuse classifier as features.** All three are deliberately inactive and refuse to load without reviewed-label artifacts that do not exist.
- **Do not claim production readiness, multi-worker coalescing, or validated real-provider behaviour.** Coalescing is process-local and JSON-only; `docs/RESULTS_LIVE_REAL_PATH.md` records two workers making two calls; real-provider completion and usage remain unverified without paid authorization.
- **Do not claim adaptive thresholding is active in the answer-aware configuration.** It is a mutually exclusive branch and does not execute when the policy artifact is set.
- **Do not quote a general accuracy percentage for semantic reuse.** The largest technical denominator anywhere in the repo is 30 rows.
- **Do not quote the "Nx faster than an 800 ms LLM call" line** that `python -m evaluation.latency` prints. `evaluation/latency.py:49` hardcodes `LLM_REFERENCE_MS = 800.0`; no provider was timed. It is correctly absent from the CSV and from `latency.tex`, and it must stay out of the report and the slides.
- **Do not describe `CACHE_MATCH_MODE=semantic` on its own as "semantic reuse enabled."** Without `ANSWER_POLICY_ARTIFACT` that configuration measurably accepts no paraphrase (F16); only the exact-match fast path serves hits.
- **Do not present the trade-off curve (`tradeoff.png`) as a threshold-selection result.** The 21-point sweep is evaluated on the same 30 pairs it is plotted from, and chapter 6 already states that thresholds were not selected on a separate validation split.
- **Do not call the stress evaluation 1,000 independent questions.** It is 200 songs × 5 variants built from three authored paraphrase templates plus the source wording and one entity swap. Report it as 200 families, say that the intervals are family-clustered, and note that paraphrase-template variance (n = 3) sits outside every reported interval (EW10).
- **Do not claim the answer-aware policy improves the cache.** On the project's own largest run it serves fewer correct hits and makes more provider calls than the static threshold; what it reduces is suspected wrong answers (F21).
- **Do not cite the deployment-capacity arm as evidence of behaviour under production limits** for the semantic policies. The 256-entry cap never binds there — they write 183 and 249 entries — and their results are identical to the unconstrained arm (F22).
- **Do not cite the CI volatility figure as a false-positive rate.** It is 0 of 4 hand-picked controls, none containing a volatility keyword; the project's own 12-case stable set gives 6 of 12 (F17).

---

# 7. Final review pass — 1 November 2026

Independent reviewer; Soul is implementing concurrently. No runtime code, test, report source, configuration or historical artifact was changed in this pass. Only this document was edited.

## 7.1 Snapshot

| Item | Value |
|---|---|
| Branch | `codex/evaluation-integrity` |
| HEAD at the start of this pass | `37dc7a7400c1811cbf501d596d3535286ce81e17` |
| **HEAD at the end of this pass** | **`1cdb80a78ebb8bd00a53cea42aa080a523af950e`** — "Verify isolated semantic demo and simplify dashboard scope". Soul committed mid-pass. |
| What that commit contains | Exactly the working-tree changes reviewed in §§7.1–7.5 and in the earlier dashboard re-review, plus one further dashboard revision noted below: `app/main.py` (+32), `app/organization.py` (+2), `app/static/dashboard.html`, `tests/test_dashboard_private_chip.py`, `tests/test_organization_scopes.py` (+7), `docs/ORG_WORKSPACE.md`, and the `release_http_20261101_v1` run. Nothing outside what this review had already inspected. |
| Still uncommitted | the full `report/` revision only: seven modified chapters, `report.tex/bib/pdf`, five new `*A_*.tex` chapters, thirteen new figures plus `build_diagrams.py`, `RECONCILIATION.md`, `REVISION_EVIDENCE.md`, two `revision_*` backups |
| New untracked | `docs/CLAUDE_REVIEW_LEDGER.md`, `evaluation/runs/release_http_20261101_v1/`, `report/chapters/4A|5A|6A|A_*.tex`, `report/figures/*.tex|pdf` plus `build_diagrams.py`, two `report/revision_*` backups, `tmp/`, `.pytest_tmp_final_fakeredis/` |
| `evaluation/` and `scripts/` source | unmodified throughout this pass |
| Executed in this pass | nothing. Two earlier read-only imports of pure decision helpers are disclosed in §1. |

### Status changes inside `1cdb80a`

- **F10 — FIXED and committed.** See below.
- **F15 — FIXED and committed.** The dashboard no longer carries a "total gateway time" field. `rlat` now sits inside the details block beside `browser HTTP time`, and its label is set at render time to `"gateway time (after admission)"` or `"stream gateway time (after handler entry)"` depending on the endpoint (`dashboard.html:289, 442`). The measurement boundary is now named rather than overstated, and the two endpoints are distinguished rather than conflated. No further action; backlog item 4 is reduced accordingly.
- **F19 — PARTIALLY addressed.** The UI half is fixed by the same change. The API half remains: `chat` still sets `t0` after `_auth` and `_check_rate_limit` while `chat_stream` sets `started` as its first statement, so the two endpoints still report different spans under the same `latency_ms` field name; and `chat_stream` still has zero `stage_ms` occurrences, so its `stage_latency_ms` carries lookup stages only, with no provider or cache-write entry. An API consumer comparing the two endpoints is still comparing unlike quantities.
- **F23 — still present.** `app/providers/mock.py:27` continues to return `f"[mock:{self.name}] Answer to: {prompt}"`.

**F10 is fixed.** `app/organization.py:301` now raises `PermissionError("Explicit workspace scope requires a workspace identifier")` before the `selected` fallback, and `tests/test_organization_scopes.py` asserts HTTP 403 for both `cache_scope="workspace"` with no workspace and with `workspace=""`. The automatic path (no `cache_scope`) still resolves server-side. Correct and complete; no further action.

## 7.2 Corrections to my earlier recommendations

| # | Recommendation | Status | Basis |
|---|---|---|---|
| 1 | F18 first-ACCEPT early exit "keeps the budget and conflict semantics identical" | **WITHDRAWN** | Proven false from code, below |
| 2 | F7 replace index invalidation with `_append` | **WITHDRAWN as stated; corrected replacement given** | `storage.put` returns a bare `bool` |
| 3 | F20 paired analysis "would very likely show a clearly positive effect" | **CORRECTED** | Prediction removed; method retained |
| 4 | F16 "the semantic path never accepts" | **CORRECTED** | Disproved by execution; the 0/30 measurement stands |
| 5 | F6 approximately 1 GB memo worst case | **CORRECTED — severity reduced to LOW** | Oversized pairs return before insertion |
| 6 | F13 regression test design | **CORRECTED** | My test was a quality test, not a contract test |
| 7 | F22 "the cap never binds" | **CORRECTED to UNRESOLVED** | Stage observations are attempts, not insertions |

### 7.2.1 F18 — early exit is a policy change (withdrawn)

`app/cache/semantic_cache.py` places three rules in the `for … else` clause, which runs **only when the loop completes without `break`**:

```
else:
    if count > limit and candidates[limit][1] >= threshold:   reason = "verification_limit_exhausted"
    elif len({item[1]["answer"].strip().casefold() for item in accepted}) > 1:
                                                              reason = "conflicting_accepted_answers"
    elif accepted:   rank, best, sim, nli_score, reason = accepted[0];  hit = True
```

A `break` on the first ACCEPT skips the whole block, so it would (a) make a lower-ranked conflicting accepted answer invisible, converting a deliberate abstention into a served hit; (b) skip the verification-limit rule; and (c) never set `hit = True`, so the structure would need rewriting as well. My claim that it preserved current semantics was wrong. The ledger's rejection is correct.

**Safe optimizations, provable and separate from any policy change:**

- **S1 — batch the shortlist into one model call.** Each candidate currently goes through `_infer` separately, acquiring the `Semaphore(1)` verifier gate per candidate. The decisions are independent, so a single `model.predict([...])` over the surviving pairs returns identical scores with one gate acquisition and one forward pass. No decision changes.
- **S2 — deduplicate identical assertions within one shortlist.** Two candidates sharing a `(stored question, answer)` pair produce the same premise and hypothesis; score once. Identical results by construction.
- **S3 — a guarded early exit that is provably equivalent.** Exit after an ACCEPT only when both hold, each checkable without a model call because answer text is already in hand from retrieval: (i) every not-yet-assessed candidate's `answer.strip().casefold()` equals the accepted answer, so the accepted set cannot grow beyond one distinct answer; and (ii) the limit rule is already decided, since `count > limit and candidates[limit][1] >= threshold` depends only on retrieval — so evaluate it before the loop. Under (i) and (ii) the `else` block's outcome is determined and skipping the remaining assessments cannot change the served result.

Anything beyond S1–S3 is a new stopping policy and needs its own stated semantics and evaluation.

### 7.2.2 F7 — the `_append` substitution is withdrawn

`storage.put` returns `bool` only (`app/cache/storage.py:292, 335`). It does not report whether the write replaced an existing `eid`, which victims it evicted, or whether another worker bumped the namespace version. `_append` therefore cannot maintain the parallel `ids/queries/answers/mat` arrays correctly: a replacement would duplicate a row, an eviction would leave a deleted entry searchable in-process, and a cross-worker write would go unseen, because the current correctness mechanism is exactly the `version` comparison in `_ensure` that invalidation forces.

**Corrected recommendation.** Keep version-based invalidation as the correctness mechanism and reduce its cost instead: (a) have `storage.put` return a small result (`stored`, `replaced_existing`, `evicted_ids`) and only then consider an incremental in-process update, still re-checking the Redis version before serving; or (b) leave the index alone and make `_build_index` cheaper by storing vectors as `float32` bytes rather than CSV text, so rebuild skips per-float parsing. Invariants any change must preserve: no entry absent from Redis is ever searchable in-process; a version change always forces a rebuild; TTL expiry cannot resurrect an entry; the per-tenant index bound in `_t` still holds.

### 7.2.3 F20 — prediction removed

Overlapping marginal intervals establish neither significance nor its absence. Corrected recommendation: add a **matched-family** bootstrap that resamples the same family IDs for both arms and reports the paired difference with explicit numerator and denominator, alongside the existing marginal intervals. State no expected direction or magnitude in advance. A statistical interval still does not address authored-label error.

### 7.2.4 F16 — the 0/30 measurement stands, the generalisation does not

The measured fact is unchanged: `evaluation/results/metrics.csv` records 0 accepted of 15 positive and 15 negative pairs for both Tier-1 rows. The generalisation was wrong. I executed the shipped decision helpers read-only:

- 35 tokens are in `_FUNCTION_WORDS` but not `_MEANINGFUL_FUNCTION_WORDS`, so changing only those cannot trip the guard: `a an at be been did do does give have how i in it its list me of on please should tell that the these this those what when where which who why with you`.
- `verify_equivalent("how do I reset the password", "how do I reset a password")` returns **`(True, "ok")`**, as does `("how do I restart the nginx service", "how do I restart nginx service")`.

Non-exact inputs therefore **can** pass the Tier-1 guard. The accurate statement is: *on this fixture it accepted none, and it rejects paraphrases that change any content or meaningful function word; determiner-only variants survive.* The startup-warning recommendation is unaffected.

The same run also shows the Tier-1 and answer-policy guard families giving **different reasons for the same pair**: "most reliable" versus "reliable" is `role_mismatch` under Tier-1 (`_ROLE_WORDS` contains `most`) but `scope_changed` under the answer policy (`_scope_terms`); "can I…" versus "how do I…" is `scope_or_tense_mismatch` under Tier-1 but `answer_type_mismatch` under the policy. Two overlapping guard families — worth knowing before narrowing either (F4).

### 7.2.5 F6 — worst case corrected, severity LOW

`app/cache/verifier.py:355` returns the `too_long` assessment **before** the insertion at `:372`, and the exception path at `:367–371` also returns before it. Only assessments that **fit the 512-token window** are memoized. A 512-token pair is on the order of 2–5 KB of text, so the realistic bound is roughly `8192 × 5 KB ≈ 40 MB`, not about 1 GB. My estimate was wrong by roughly an order of magnitude and the finding largely dissolves as the code stands.

What survives is an **interaction constraint on F5**: if F5 adds negative-result memoization for `too_long`, the raw oversized premise and hypothesis would then be retained, bounded only by `max_cache_entry_bytes` (64 KB default) — at which point the original figure becomes reachable. F5's fix must therefore memoize `too_long` under a **hashed key holding only status and token count**, never the raw strings. Keep the hashed-key recommendation, justified by this interaction rather than by current memory.

### 7.2.6 F13 — a contract test, specified separately from quality

My proposed test (identical pair above `accept_at`, contradictory pair below `reject_below`) is a **semantic quality** test. A correct raw-logit path could fail it on a hard pair, and a double-softmaxed path could still pass it on extreme pairs, so it does not test the transformation contract. Replace it with two separate tests:

- **Transformation contract.** Call `model.predict([(premise, hypothesis)])` on the pinned model and assert the returned vector is *not already normalised*: its length equals `num_labels`, and its values do not sum to 1 within tolerance and/or at least one is negative. Then assert `id2label` contains exactly one label whose lowercase form contains `entail`, and that the reported probability equals an explicit softmax of the returned vector at that index. This fails loudly if a library upgrade begins applying an activation internally.
- **Quality**, separate and opt-in: any threshold-crossing expectation about particular sentence pairs.

### 7.2.7 F22 — downgraded to UNRESOLVED

`app/main.py:833` sets `stage_ms["cache_write"]` unconditionally after `_cache_store` returns, and `_cache_store` returns `"stored"`, `"ineligible_or_full"`, `"write_timeout"` or `"write_failed"`. A `cache_write` stage observation is therefore an **attempt**, not a successful unique insertion. My inference that 183 and 249 writes sit below the 256 cap, so the cap never bound, is unsupported.

The saved data shows something narrower: the semantic arms recorded `expiry_or_eviction_misses = 0` and outcome counts identical to the unconstrained arm, so no eviction-caused miss was observed. That cannot distinguish "no eviction occurred" from "entries were evicted but never requested again". Two further obstacles: the stress tenant is `t_<hex>`, which takes the **unscoped** `storage.put` path, and per F9 that path never increments the eviction counter, so the counter route is unavailable for this workload; and TTL expiry is not separated from repeated-key overwrites in the saved rows. Resolving this needs a purpose-built capacity experiment recording initial occupancy, successful insertions, peak occupancy, eviction counters and TTL, with enough distinct eligible entries to force eviction. Until then the deployment arm should be described as *not demonstrated to exercise capacity pressure*, not as *the cap never bound*.

## 7.3 New findings

### F23 — HIGH for the demonstration · confirmed · mock answers embed their own prompt, which poisons the answer-aware assertion

**Where** `app/providers/mock.py:_answer` returns `f"[mock:{self.name}] Answer to: {prompt}"`, against `app/cache/answer_policy.py:187–188`, which builds premise `"The answer to {stored} is {answer}."` and hypothesis `"The answer to {incoming} is {answer}."`.

**Mechanism** When the cached answer is a mock placeholder it literally contains the *stored* question. The hypothesis then reads "The answer to **Q2** is [mock] Answer to: **Q1**." — an assertion close to self-contradictory for any Q2 ≠ Q1. Entailment collapses however good a paraphrase Q2 is.

**Evidence — live, at the reviewed commit.** `evaluation/runs/release_http_20261101_v1/observations.json`, real Redis Stack, MiniLM, prewarmed pinned NLI, mock profiles:

| Case | Cached answer origin | Outcome | NLI |
|---|---|---|---:|
| `carol_fixture_paraphrase` | explicitly seeded factual answer | **HIT**, rank 1, similarity 0.9862 | **0.9208** |
| `carol_generated_paraphrase` | mock placeholder | **MISS**, `answer_contradiction_or_irrelevance` | **0.0133** |

Same gateway, same workspace, comparable paraphrase. The only difference is whether the cached answer was a seeded sentence or a mock placeholder. The run's README records the second as "a remaining valid-reuse miss" but does not attribute it to the placeholder format.

**Consequence for the demonstration** In any mock-backed demo, semantic reuse can be shown **only on seeded answers**. Every answer the mock provider generates during the demo will be rejected on its first paraphrase, so a live audience asking two phrasings of a fresh question sees two provider calls and concludes the cache does not work. It also means mock-backed runs systematically understate the verifier, so their miss counts are not a clean measure of F1.

**Smallest justified fix** Make the mock answer independent of the prompt text — for example a deterministic answer keyed by a hash of the prompt, or a short fixed sentence per prompt — so the placeholder no longer embeds the question. This touches a development provider only: no policy, threshold or artifact changes.

**Invariants to preserve** Determinism per prompt (tests depend on it), the `[mock:…]` marker so the dashboard still labels it a placeholder, and no change to `implicit_completion_is_safe` or the completion contract.

**Regression needed** Assert that a mock answer does not contain the prompt text, plus one end-to-end assertion that a paraphrase of a mock-answered question is not rejected because of the placeholder format.

### F24 — MEDIUM · confirmed coverage gap · the RediSearch tenant filter has no automated assertion

**Where** `tests/test_organization_scopes.py::test_semantic_retrieval_excludes_unauthorized_private_candidate`, and the helper `settings_for`, which hardcodes `vector_backend="inproc"` as an explicit `Settings(...)` kwarg — so the Redis Stack CI job's environment does not override it.

**What the test asserts** Carol's lookup returns `candidate_count == 0` and `note == "empty_cache"`. With the in-process backend each tenant has its own dict entry, so an empty result for a tenant that stored nothing is structurally guaranteed; the assertion holds even if the RediSearch tenant TAG filter were removed entirely. The test never populates a shared index from which an unauthorized candidate must be excluded.

**What is covered elsewhere** `app/cache/redisearch_store.py:smoke_test()` does assert cross-tenant isolation ("tenant isolation failed: another tenant saw the entry"), but it is a `__main__` script, not collected by pytest. `tests/test_live_redis.py` exercises real Redis across worker processes using a single tenant per test, so it contains no isolation assertion either. The `knn` TAG filter and its escaping are unasserted by any automated test.

**Not a runtime defect.** The filter code reads correctly: `knn` escapes non-alphanumerics into the TAG query and independently re-checks `row[b"tenant"] == tenant.encode()` on every returned hash, while `read_candidate`, `read_overlay_candidate` and `touch_candidate` each verify the key prefix and the tenant field. Isolation is additionally enforced by the key scheme. This is missing coverage of a guarantee that currently appears sound.

**Smallest justified fix** One test parameterised over both backends that seeds tenant A, queries as tenant B with a deliberately similar prompt, and asserts tenant B sees `candidate_count == 0` — skipped for RediSearch unless `REDIS_URL` is set, mirroring `test_live_redis.py`'s guard.

## 7.4 Test-coverage matrix

Mocked boundary = what the test replaces. "Can pass while broken?" asks whether the stated guarantee could be violated with the test still green.

| Guarantee | Implementation | Test / assertion | Mocked boundary | Saved execution evidence | Can pass while broken? | Uncovered scenario |
|---|---|---|---|---|---|---|
| Cross-org and cross-employee private isolation | `organization.scoped_tenant` key scheme | `test_shared_private_cross_org_and_forged_scope` — MISS for another org, 403 for a forged scope | mock provider; fakeredis | release probe: `different_org` MISS in its own private scope, `unauthorized_workspace` 403 | No, for the key scheme | — |
| Authorized workspace sharing | same, plus `scope_decision` | `test_server_default_shares_generic_technical_requests_without_scope_fields` | mock provider; **exact mode, hash embeddings** | release probe `carol_fixture_paraphrase` HIT with `lookup_scope=workspace` | No | sharing through RediSearch top-k is covered only by the release probe, not by pytest |
| Semantic retrieval excludes unauthorized candidates | `rs.knn` TAG filter plus per-row tenant recheck | `test_semantic_retrieval_excludes_unauthorized_private_candidate` | **`vector_backend` pinned to inproc** | `smoke_test()`, manual and not collected | **Yes — F24** | populated shared index with a competing tenant |
| Revocation during lookup | `_principal` recheck before serving a HIT | `test_revocation_during_hit_lookup_prevents_serve` — patches `cache.lookup` to flip status mid-request, asserts 401 | the lookup wrapper only; real directory file replace | — | No | revocation between the HIT check and the response write |
| Revocation after generation | `_still_authorized` before the write | `test_revocation_after_generation_prevents_shared_write` — asserts `credential_changed_no_store`, then 401, then Carol MISS | `_generate_answer` wrapper | — | No | the streaming equivalent is asserted only indirectly |
| Rotation preserves subject scope | digest → Principal map | `test_rotation_and_revocation_preserve_subject_scope`, `test_live_revocation_and_rotation_without_cache_orphan` | fakeredis | — | No | — |
| Provider-profile / secret-rotation cache boundary | `profile_compatibility` inside the tenant key | `test_concurrent_profiles_are_isolated` | mock profiles | — | Partial — isolation asserted, **orphaning on secret rotation is not** | rotate the `secret_env` value; assert old entries unreachable and the behaviour documented |
| Candidate mutation and expiry before serving | re-read and compare in `_lookup` | `test_changed_inproc_answer_after_policy_decision_calls_provider`, `…redisearch_answer…`, `…expired_redisearch_candidate…`, `test_redisearch_discards_hash_changed_after_search` | NLI stub; RediSearch path monkeypatched per test | — | No — these are strong | — |
| Top-k conflict, budget and limit | the `for…else` block | `test_conflicting_accepted_answers_abstain`, `test_verification_budget_timeout_is_a_miss`, `test_unchecked_high_similarity_candidate_forces_abstention` — assert the exact `note` through real HTTP | **the NLI model only** (`AlwaysEntails.entail_prob`) | combined and applicability runs | No, for the selector logic | the stub has no `assess`, so `too_long` never reaches `decide` end-to-end |
| Provider completion validation | `openai_compat.stream_events` plus `_generate_answer` | `test_complete_answer_and_usage_only_event_are_cached`, `test_length_filtered_and_missing_finish_are_never_cached`, `test_terminal_event_cannot_be_revised_or_followed_by_content` — assert 502 / `event: error` / no `[DONE]` / not cached | httpx transport stub emitting crafted SSE | release probe `stream_complete` | No — genuinely thorough | a real provider is never exercised (no paid authorization) |
| JSON and streaming failure paths | both handlers | `test_first_token_timeout_returns_504_and_is_not_cached`, `test_partial_stream_never_caches`, `test_cache_write_failure_completes_stream`, `test_response_size_error_is_distinct_and_uncached`, several parameterised over both endpoints | transport stub | — | No | client disconnect mid-stream (F14) |
| Request coalescing | `SingleFlight` | five tests asserting call counts, follower timeout, leader cancellation, capacity bound and `_active` emptiness | pure unit, no HTTP | — | No, for the primitive | the HTTP-level key (`tenant\0subject\0prompt`) is unasserted; streaming has no coalescing at all (F7a) |
| Scope and organization quotas | `_put_scoped` WATCH transaction | `test_scope_and_organization_quota_across_clients`, `test_byte_limit_fails_closed_without_partial_write`, `test_expired_recently_touched_entry_does_not_evict_live_entry`, `test_old_expiry_score_never_deletes_live_hash` | fakeredis | `test_scoped_quota_and_hit_recency_across_worker_processes` on real Redis | No | app/Redis clock skew (F8) is invisible under fakeredis |
| Real Redis versus fakeredis | both backends | `test_live_redis.py` — separate worker **processes**, parameterised exact and semantic, atomic Lua bucket, vector-schema mismatch fails closed | none; real Redis required | CI job `test-with-redis` | No | no cross-tenant isolation assertion (F24); one tenant per test |
| NLI window handling | `NliVerifier.assess` | `test_nli_input_bounds.py` — boundary, one-over, no poisoning, scope-partitioned memo, purge | **fake tokenizer, `WINDOW = 12`** | lockbox 596-token row | No, for the logic | the real pinned model's window is never asserted (F2 regression) |
| Readiness reflects the active mode | `_health_details` | `test_policy_prewarm.py` (three tests), `test_policy_runtime_identity.py` | fakeredis | release probe `ready` block | No | sticky-unavailable recovery is unasserted because there is none (F5) |

**Systemic observation.** The default suite runs `EMBEDDING_BACKEND=hash`, `VECTOR_BACKEND=inproc`, `CACHE_MATCH_MODE=exact`, `VERIFIER_NLI=false`, mock provider and fakeredis. Semantic retrieval quality, RediSearch and the real NLI model are therefore exercised by the Redis Stack CI job and by saved runs rather than by a default `pytest` invocation. That is a reasonable engineering choice, and it means a green local run is not evidence about semantic behaviour.

## 7.5 Configuration and deployment consistency

| Question | Finding |
|---|---|
| What does a fresh documented setup start? | `docker compose up --build` starts Redis Stack (loopback-bound, 512 MB, `noeviction`) and the gateway on 8000 with `VECTOR_BACKEND=redisearch`, `EMBEDDING_BACKEND=minilm`, `LLM_PROVIDER=mock`, `CACHE_MATCH_MODE=exact`, no answer policy and no prewarm. `scripts/start_org_demo.ps1` adds `docker-compose.org-demo.yml`, switching to semantic plus the policy artifact, prewarm, and the mock organization directory. |
| Which mode, policy and guards are active? | Base compose: exact, no policy, both experimental guards off. Org demo: semantic, `answer_policy_v1.json`, prewarm on, applicability and technical guards off. `/health` reports all of these, and the release probe's `ready` block confirms the reporting is accurate. |
| Are required artifacts inside the container? | Yes for the policy artifact: `app/cache/artifacts/answer_policy_v1.json` lives under `app/`, which the `Dockerfile` copies. |
| Does the organization directory reach the container? | Yes, through the documented path only. `docker-compose.org-demo.yml` bind-mounts `./config:/app/config:ro` and sets `ORGANIZATION_CONFIG_PATH=/app/config/organizations-demo.json`. The `Dockerfile` copies only `app`, so the base image contains no `config/` — which is correct, because base compose sets no directory path. |
| Does model availability require network access? | Yes on first run. The image pre-creates `/home/appuser/.cache/huggingface` but downloads nothing. `org-demo` and `org-live` mount a named `model-cache` volume so the download survives recreation; **base `docker-compose.yml` has no such volume while still setting `EMBEDDING_BACKEND=minilm`**, so a plain `compose up` re-downloads MiniLM on every container recreate. `docs/ORG_WORKSPACE.md`'s "the Docker volume persists them" is accurate for the path it documents. |
| Volume persistence, Redis memory, model memory, worker duplication | Redis runs `--maxmemory 512mb --maxmemory-policy noeviction` with a `redis-data` volume, and `validate_production` refuses production without a finite `maxmemory`. Model memory is documented from measurement (`nli_memory.json`: +680.9 MB RSS at prewarm, explicitly process-level rather than weight size). Worker duplication is documented honestly — coalescing is process-local and two workers make two calls. |
| Ports and administrative/demo controls | Redis and RedisInsight bind to `127.0.0.1`; the gateway publishes `8000:8000` on all interfaces. In development `/health` and `/ready` return the full configuration **unauthenticated**, while production returns only `{"status": …}`. `/admin/cache/clear`, `/admin/cache/occupancy` and `/admin/demo/restore` all require a valid key, and demo restore is additionally gated behind seven simultaneous conditions plus an `hmac.compare_digest` on the demo key. Appropriate as a development default; for a demo on a shared network, publish `127.0.0.1:8000:8000`. |
| Accidental paid provider, or silent mock? | Paid use requires explicitly setting `VERIGATE_COMPOSE_PROVIDER` **and** a key; the compose comment states that intent, and the compose environment overrides a stray local `.env`. The reverse risk — setting `OPENAI_API_KEY` but forgetting the provider variable and silently getting mock answers — is mitigated by the dashboard labelling mock output "mock placeholder" and by `/health` listing the active providers. |
| Do readiness checks match the active mode? | Yes. `_health_details` validates the RediSearch index only when `vector_backend == "redisearch"` and the mode is semantic, and checks the verifier only when a policy artifact is loaded. |

Two deployment consequences of existing findings appear only in a container:

- **F5 in Docker.** `HEALTHCHECK` polls `/health`, which returns 503 when a policy artifact is configured and `answer_verifier.unavailable` is set. Because that flag latches permanently, one transient model-load failure marks the container unhealthy for its whole lifetime, with restart the only recovery. This raises F5's priority for any containerised demonstration.
- **Redis `noeviction` under memory pressure.** Cache writes fail and are absorbed (`write_failed`, provider answer preserved), but the rate limiter and budget counters also write to Redis, and their failure path is `503 "admission unavailable"`. Redis memory exhaustion therefore degrades the whole gateway to fail-closed 503s rather than to a cache-less but serving gateway. Defensible, but it should be a stated operational property rather than a surprise.

## 7.6 Saved logs against claimed results

- `technical_combined_fresh_20261101_v1/results_reverse/combined/gateway.log` and `technical_applicability_live_20261101_v1/results_complete/applicability_on/gateway.log` contain **zero** error-, exception- or traceback-matching lines, and no verifier-unavailable, `too_long` or budget-exhaustion warnings. Structured event counts reconcile with the published summaries: 8 `cache_hit` of 25 for the combined-reverse arm (summary `valid_reuse: 8`) and 4 of 25 for applicability-on (`valid_reuse: 4`).
- The new `evaluation/runs/release_http_20261101_v1/` is a complete, internally consistent 13-request probe at `37dc7a7` against real Redis Stack with a prewarmed pinned NLI model. Its `ready` block matches the documented org-demo configuration, every row carries HTTP 200 except the intended 403, and the README's narrative matches the row-level records, including two streaming rows that ended with final metadata and `[DONE]` and no error event. Its one substantive claim, "a remaining valid-reuse miss", is corroborated by the row (`nli 0.0133`) but under-attributed; see F23.
- No historical failure is being presented as current. The retained `technical_applicability_live_.../results/` first attempt is documented as a failed summary-writer run, is excluded from the published comparison, and is excluded from the CI verifier, which checks only `results_forward_verified` and `results_reverse`.
- I found no saved evidence of a full test-suite execution at this commit. `report/generated/checks.tex` records 303 passed, 7 skipped, 0 failures from `evaluation/results/checks.json`, but that artifact is produced by `scripts/record_test_summary.py` from an earlier run and is not tied to `37dc7a7` within the file. **No claim in this review asserts that tests currently pass.**

## 7.7 Verifier improvement design review

Reviewing `app/cache/reuse_verifier.py`, `scripts/prepare_reuse_data.py`, `scripts/train_reuse_verifier.py` and the artifact gates.

| Question | Finding |
|---|---|
| Input representation | `format_input` produces `("Stored question: …\nStored answer: …", "Incoming question: …")`. **The answer appears once, not twice.** This is structurally better than the deployed assertion: it roughly halves the answer's token cost, materially raising the usable answer length before `too_long`, and it keeps the three fields explicit instead of embedding them in a natural-language sentence. |
| Realistic long answers | Still bounded. `assess_reuse` compares the `input_ids` length against `min(max_position_embeddings, model_max_length)` and returns `too_long` → VERIFY. Better headroom, same ceiling. |
| Label mapping and model identity | Strong. `num_labels != 1` is rejected; the score is a sigmoid over the single logit with `torch.isfinite` and shape checks. The manifest pins `format_version`, `base_model`, `base_revision` (checked against the runtime `nli_revision`) and `input_format`; every listed file is SHA-256 verified with a path-escape check; the manifest hash becomes `identity`, is folded into the cache namespace, and forms part of the memo key. |
| Family separation | `split_rows` holds out **whole sources**, then rejects any task family crossing splits and any near-template overlap after normalisation. Stronger than a random split. |
| Train / calibration / test separation | Genuinely separated by source, with calibration and test each taking a distinct held-out source and every split required non-empty. |
| What is still missing | Independently reviewed labels. `load_rows` accepts only `expert_reviewed` or `source_document_verified` provenance and requires at least three independent sources, while `prepare_reuse_data.export` stamps a single `source` per workload directory — so the existing export cannot satisfy the gate. `PROJECT_PROGRESS.md` records 75 development pairs against a 600–4,000 requirement. |
| Does deployment refuse bad artifacts? | Yes, at several layers: `calibration.validated is not True` raises; a changed file hash raises; a base-revision mismatch raises; and `SemanticCache.__init__` refuses the adapter unless semantic mode, an answer policy and prewarm are all enabled. |

**One bounded next experiment — isolate the representation, not the model.**

*Rationale.* F2 and F23 both point at the **assertion format** rather than model capacity: the answer is charged twice against the window, and when the answer text contains a question the assertion becomes self-defeating. The reuse adapter already uses a single-sided three-field format. Before anyone trains anything, measure whether that representation alone changes decisions, using the **already-pinned** model and no new labels.

*Experiment.* Offline and evaluation-only. Re-score the frozen `technical_bidirectional_lockbox_20261101_v1` workload — 30 rows, including the 1,620-character `long_config_answer` family — with the pinned `cross-encoder/nli-deberta-v3-xsmall`, comparing the deployed two-sided assertion against a one-sided three-field framing. Change nothing else: same model, same revision, same thresholds, same rows, same labels.

*Prerequisites.* The frozen workload and its labels; the pinned model available offline (`HF_HUB_OFFLINE=1`); a new versioned run directory; no gateway or policy change.

*Gates.* Report paired per-row decision changes with denominators, the `too_long` count before and after, and valid / invalid / ambiguous counts separately. Promote the representation only if `too_long` falls **and** neither invalid accepts nor ambiguous accepts increase. Record wall-clock per call. No threshold may move.

*Fallback.* If the one-sided framing does not reduce `too_long` without new bad accepts, record a negative result, keep the deployed formulation, and treat the classifier work as still blocked on labels. A representation that passes this gate is still only a candidate; it would need its own frozen, family-disjoint validation before becoming a default.

This does not promise that any representation or model change fixes F1. It isolates one variable cheaply, and the outcome decides whether the expensive labelled-data effort should target the formulation or the model.

## 7.8 Ranked implementation backlog

Classes: **A** confirmed defect · **B** intentional trade-off · **C** evaluation gap · **D** suspected risk needing reproduction · **E** future enhancement.

Order below is the recommended implementation order. Items 1–4 are independent of each other; 5 should follow 1 so the batching measurement is not taken against poisoned assertions; 11 depends on 2; 12 depends on 7.

| # | Item | Class | Problem and user-visible consequence | Evidence and confidence | Smallest justified change | Invariants the fix must preserve | Required regression or evaluation | Depends on | Needed for |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Mock answers embed the prompt (F23) | A | Every mock-generated answer is rejected on its first paraphrase, so a live demo shows the cache failing on anything not pre-seeded | Live release probe: seeded 0.9208 ACCEPT versus generated 0.0133 REJECT. **High** | Make `MockProvider._answer` not contain the prompt text | Determinism per prompt; the `[mock:…]` marker; the completion contract | Assert a mock answer excludes the prompt; one paraphrase end-to-end | — | **Demonstration** |
| 2 | Volatility over-bypass (F3) | A | Ordinary technical questions containing `current`, `score`, `latest`, `live` or `recent` are never cached or reused, in exact mode too | Reproduced 6/12 on the project's own set; 12/12 technical probes bypass. **High** | Two-part narrowing per §3 F3, including the four unconditional words | All 12 volatile dev cases still bypass; unknown intent still bypasses | Extend the dev TSV with technical contrast cases; report both denominators | — | **Demonstration** |
| 3 | Verifier latches unavailable; `too_long` not memoized (F5) | A | One transient model-load failure makes the container permanently unhealthy and disables all reuse until restart | Code path plus the Docker `HEALTHCHECK` on `/health`. **High** | Failure count and cooldown instead of a boolean latch; memoize `too_long` under a hashed key holding status and token count only | Fail-closed during cooldown; `last_failure_category` still in `/ready`; never retain raw oversized strings (F6 interaction) | Repeated oversized input tokenizes once; one transient failure recovers after cooldown; no retry storm | — | Engineering reliability |
| 4 | API timing spans still differ between endpoints (F19 residue; F15 fixed in `1cdb80a`) | A | The dashboard label is now correct, but `/v1/chat` and `/v1/chat/stream` still report different spans under one `latency_ms` field, and streaming `stage_latency_ms` omits the provider and cache-write stages | Verified after the commit: `t0` still follows `_auth` and `_check_rate_limit`; `chat_stream` has zero `stage_ms` occurrences. **High** | Give `chat_stream` a `stage_ms` dict covering admission, provider and cache write, and document the two spans in the API response or align them | Do not silently redefine an existing metric — version the change; keep handler, browser and first-token times distinct; stages need not sum to the total | Controlled-delay test asserting streaming reports provider and cache-write stages, and that each endpoint's documented span matches what it measures | — | Reliability (demonstration risk already resolved) |
| 5 | Batch and deduplicate shortlist verification (F18 → S1, S2) | A (efficiency) | Up to five sequential gated model calls per lookup; NLI dominates warm latency | Loop structure plus saved stage timings. **High** | One `predict` over the surviving pairs; skip duplicate assertions | Identical decisions and identical `candidate_trace`; budget and conflict semantics untouched | Byte-identical traces before and after on a frozen run; measure warm p50/p95 on the same runner | 1 | Reliability |
| 6 | LRU mixes application and Redis clocks (F8) | A | Under clock skew, recently served entries can be evicted before cold ones | Two clock sources writing one ZSET. **High** for the mechanism; unobservable under fakeredis | `pipe.time()` in `storage.touch` | Scoped and unscoped paths keep their current quota semantics | Skew test against real Redis `TIME` | — | Reliability |
| 7 | Legacy eviction counter never increments (F9) | A | `/admin/cache/occupancy` always reports zero evictions for legacy keys, and the counter route is unavailable to the stress tenant | Unscoped `put` deletes victims without `incrby`. **High** | Increment and expire the counter in the unscoped path | No change to quota or eviction behaviour | Non-zero count after forced eviction on a legacy tenant | — | Reliability; unblocks 12 |
| 8 | Semantic mode without an artifact (F16, corrected) | B, A for documentation | Flipping one documented variable yields a policy that rejects every content-token paraphrase, so the cache looks broken | 0/30 measured; determiner-only variants do pass. **High** | Startup warning when semantic mode has no artifact, plus one line in `.env.example` | Do not alter `_token_diff_reason` to improve an inspected fixture | Assert the warning fires; pin current behaviour as intentional | — | **Demonstration** |
| 9 | RediSearch tenant filter unasserted (F24) | C | A regression in the TAG filter or its escaping would fail no test | The test pins `inproc`; the smoke script is not collected. **High** | One backend-parameterised isolation test, skipped without `REDIS_URL` | Keep the existing in-process assertion | The new test itself | — | Reliability |
| 10 | Paired analysis of the stress comparison (F20) | C | The strongest available result is reported in a form that settles nothing | Overlapping marginal intervals. **High** | Matched-family bootstrap of the difference, reported with denominators | Keep the marginal intervals; state no expected direction | The new interval, computed over an identical family set in both arms | — | Report quality |
| 11 | CI accuracy gate and volatility controls (F17) | C | The only enforced accuracy number uses a fixture the codebase forbids as a test set, with an in-sample sweep and four easy controls | Code plus `datasets.py:40`. **High** | Point `evaluate_volatility` at the 12-case dev TSV; keep the fixture as a smoke regression; state in the report what the Tier-1 rows show | Do not overwrite historical artifacts | Assert the gate uses the dev set and does not regress | 2 | Report quality |
| 12 | Capacity behaviour under eviction (F22, unresolved) | C | No evidence that the semantic policies behave correctly under capacity pressure | Stage observations are attempts, not insertions. **Medium** | A separately versioned capacity experiment recording initial occupancy, successful insertions, peak occupancy, eviction counters and TTL | Do not modify historical runs | Require eviction evidence, not necessarily an eviction-caused miss | 7 | Report quality |
| 13 | Streaming disconnect lifecycle (F14) | D | A breaker lease and upstream connection may be held if a client never iterates the body | Not reproduced; self-heals through the probe TTL. **Low to medium** | Reproduce with a disconnect test first; fix only if demonstrated | Bounded cleanup; no partial cache write | Disconnect before and during iteration; assert the generator closed and the lease released | — | Reliability |
| 14 | Score-transformation contract (F13) | D | A library upgrade could silently change every accept and reject with no test failing | Pinned today, unasserted. **Medium** | Contract test per §7.2.6, kept separate from quality tests | Keep quality expectations in their own opt-in test | The contract test itself | — | Reliability |
| 15 | Representation experiment (§7.7) | E | Determines whether the verifier problem is formulation or model, before any labelled-data spend | Design reviewed, not run. Confidence not applicable | Offline paired re-score of a frozen workload with the pinned model | No threshold change; no new labels; a versioned run directory | The gates in §7.7; a negative result is an acceptable outcome | — | Research |
| 16 | Structural guard narrowing (F4) | E | Superlative and polar paraphrases are rejected before any model call, by two overlapping guard families | Mechanism confirmed; prevalence unmeasured. **Medium** | Freeze a validation set *first*, then narrow | Do not broadly remove guards; check applicability before wording | Valid-reuse and incorrect-accept counts reported separately | 15 | Research |

### Classification summary

- **A — confirmed defects:** 1, 2, 3, 4, 5, 6, 7 (and 8 as a documentation defect over an intentional policy).
- **B — intentional trade-offs:** the conservative token-diff policy behind 8; privacy classification restricting some technical sharing (F11); profile and secret-rotation cache partitioning (F12); fail-closed admission under Redis failure.
- **C — evaluation gaps:** 9, 10, 11, 12, plus EW10's template redundancy and the absence of two-reviewer technical labels.
- **D — suspected risks needing reproduction:** 13, 14.
- **E — future enhancements:** 15, 16, and the task-reuse classifier once labels exist.

## 7.9 The five most valuable next changes

1. **Stop the mock provider echoing the prompt (item 1).** One function. Without it the demonstration shows the cache failing on every freshly generated answer, and every mock-backed run understates the verifier.
2. **Narrow the volatility gate, including the four unconditional words (item 2).** Reproduced, demo-visible, and the only sub-contribution with a labelled set showing a 50% false-bypass rate.
3. **Give the verifier a recovery path and memoize `too_long` safely (item 3).** Turns one transient model error from "permanently unhealthy container" into a retry, and is a prerequisite for not regressing memory.
4. **Batch and deduplicate shortlist verification (item 5).** The only latency work that is provably decision-preserving; the early-exit idea it replaces is withdrawn.
5. **Add the RediSearch tenant-isolation test (item 9).** The strongest product guarantee — cross-tenant isolation under semantic retrieval — currently has no automated assertion that would fail if the TAG filter regressed. Cheap, and it protects the claim the project most needs to keep.

*(The dashboard timing relabel that previously occupied this list was completed in `1cdb80a`; the remaining API-span work is backlog item 4 and is no longer demonstration-critical.)*

## 7.10 Remaining review gaps

- **Not executed, so not verified.** Every finding remains static analysis plus saved artifacts. No test run, no gateway start, no provider call. There is no saved evidence that the suite passes at `37dc7a7`; the 303/7 in `checks.tex` comes from an earlier, untied run.
- **Not reviewed.** The LaTeX report revision in progress — seven modified chapters, four new chapters, thirteen new figures, `RECONCILIATION.md` and `REVISION_EVIDENCE.md` — which is now the largest uncommitted change in the tree. Also 9 of 18 `evaluation/*.py` modules (`gold_model.py`, `gold_verifier_study.py`, `cascade.py`, `stream*.py`, `reproduce.py`, `risk_guarantee.py`, `backend_compare.py`, `train_accept.py`), roughly 51 of 60 scripts including the subject-guard, pilot and judge runners, most saved CSV artifacts, all but three gateway logs, and the Grafana, Prometheus and `render.yaml` configuration.
- **Read but not exhaustively traced.** `_put_scoped`'s 100-iteration WATCH transaction under genuine contention: I verified its structure, its invariants and its tests, but did not reason through every interleaving.
- **Not knowable from here.** Real-provider completion and usage behaviour, production traffic distribution, and any claim about answer correctness — each needs authorization or human review that does not yet exist.
