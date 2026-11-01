# Isolated semantic HTTP release probe (1 November 2026)

`observations.json` records 13 requests to an isolated local gateway. The gateway
image contained Python code from `37dc7a7400c1811cbf501d596d3535286ce81e17`;
the dashboard edit in progress did not affect this HTTP run. The probe used real
Redis Stack, pinned MiniLM embeddings, pinned NLI, the existing answer policy,
required prewarming, and two distinguishable **mock** organization profiles.
The applicability/technical guards and untrained reuse classifier were off.
No paid provider was contacted. The factual decorator answer was explicitly
seeded; other generated answers were mock placeholders.

The test used a separate ephemeral Redis Stack container, a second gateway on
port 8002, and `.tmp/organizations-demo.json`. It did not clear or seed the
normal demo Redis. To repeat it, start the normal Docker stack, create a fresh
directory with `python -m scripts.provision_organization init-demo
.tmp/organizations-demo.json` followed by `ensure-demo-default` for the same
path, then start a separate Redis Stack container on the `verigate_default`
network named `verigate-release-redis`. Start `verigate-gateway:latest` as
`verigate-release-test` on that network with port 8002, its own Redis URL
`redis://verigate-release-redis:6379/0`, the directory bind-mounted as
`/app/config/organizations-demo.json`, and the environment from
`docker-compose.org-demo.yml`. Run `scripts/seed_org_demo.py` inside the test
gateway, then `powershell -File evaluation/runs/release_http_20261101_v1/run.ps1`.
The probe writes a fresh local `.tmp/release_probe.json`, leaving this saved
observation file unchanged. Remove only the two named test containers afterward.

Observed: the authorized colleague reused the seeded answer with rank 1,
similarity 0.9862, NLI score 0.9208, no provider invocation, and 13.64 ms
gateway latency. An employee's completed mock response was stored in the
workspace, but the colleague's valid paraphrase missed: the model rejected that
specific placeholder answer. The two requests took 234.64 and 277.73 ms.
This is a **remaining valid-reuse miss**, not an answer-quality error estimate.
Another organization missed in its own private scope; an unauthorized workspace
request returned 403. A personal request stayed private for each employee.
The secret-bearing request bypassed storage. Changed action, environment, and
version requests fell through to the mock provider. Streaming completed and
stored one answer, then served its exact repeat from cache; both emitted final
metadata and `[DONE]` without an error event.

This small, selected demonstration does not establish production semantic
accuracy, provider answer quality, latency distributions, or cost savings.
