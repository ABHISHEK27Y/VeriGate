# Evidence-bound answer applicability

The checkout began at `2e0e9bccdb367c8994c82bd77fa1d303731cb526`.
The previous engineering fixes and historical runs were preserved. The prior
technical NLI comparison's Terraform plan/apply invalid acceptance and four
underspecified approvals were inspected as development evidence. Each had its
intended cached candidate retrieved above the similarity floor. The stored
answers were sufficient for the **stored** task, but not necessarily for the
changed or broader incoming task. Existing structural checks passed; the
forward answer assertion NLI scores were .928–.979 and authorized acceptance.
No input was truncated. This is an applicability failure, not proof that any
stored answer was factually false.

The experimental check extracts only supported facets: requested action, HTTP
method, environment, version, permission, a `marked` test selector, and named
workspace/namespace/queue/topic/client/server values. A facet matters only
when one value appears in both the stored question and the specific cached
answer. An explicit different value rejects that candidate; a missing value
abstains. A missing word that is not anchored in the answer goes to the
unchanged answer policy. Aliases such as plan/preview and prod/production are
normalized. Multiple values and unsupported language are left to the existing
policy. This is bounded syntax evidence, not general entity understanding or
factual verification.

The 32-case, eight-family [workload](workload.json) and independent stipulated
labels were committed at `4e08cab` before either variant was evaluated. Both
used the same fixed candidate, pinned MiniLM similarity, NLI model and policy
artifact. All 16 valid candidates cleared the retrieval floor.

| Frozen variant | Valid reuse | Incorrect accepts | Ambiguous approvals | VERIFY / all | Decision p95 | NLI calls |
|---|---:|---:|---:|---:|---:|---:|
| Unchanged | 9/16 | 1/8 | 5/8 | 7/32 | 94.733 ms | 32 |
| Experimental applicability | 9/16 | 0/8 | 0/8 | 14/32 | 86.639 ms | 16 |

Two valid omissions explicitly benign under their stored answers (generic
Nginx restart and Nomad status inspection) remained ACCEPT. The experimental
check caught the invalid Ansible apply-versus-preview request, and all five
baseline-approved underspecified requests. It did not rescue seven valid
requests the baseline already declined. Some additional valid requests received
an applicability abstention instead of NLI uncertainty; this reveals extraction
limits and is **not** counted as improved recall. The code is exposed only by
`ANSWER_POLICY_APPLICABILITY_GUARD=true`; exact matching remains the deployment
default, and this guard is off by default even in opt-in semantic mode.

On one Windows CPU process, RSS was 54.3 MB initially, 571.3 MB after MiniLM,
798.2 MB after NLI prewarm, and 807.7 MB after both variants. The variants share
one model, so this run does not isolate per-variant memory. Warm verifier-call
median/p95 was 74.412/94.606 ms unchanged and 74.738/99.442 ms experimental;
the experimental path avoided 16 NLI calls on these cases. These are local
fixed-candidate timings, not HTTP end-to-end latency. The saved row-level
decisions and hashes are in `results/`.

This narrow controlled set supports an **experimental opt-in**, not a global
production safety claim. It does not cover arbitrary targets, implicit
requirements, multi-step answers, real traffic prevalence, or truth of the
cached answer. The current default is unchanged. Automatic workspace selection,
private isolation, completion checks, deadlines, candidate traces, and
historical results were preserved.
