# Live Redis + MiniLM gateway checkpoint

This is a software benchmark of VeriGate's live HTTP path, not an independent
answer-quality evaluation. It ran on GitHub Actions [run 40997695780](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/40997695780),
source commit `38d021e106f7682853a658f999d79144ba80aaae`. The [real semantic
manifest](../evaluation/runs/real_semantic_38d021e_v1/manifest.json),
[request rows](../evaluation/runs/real_semantic_38d021e_v1/requests.csv), and
[summary](../evaluation/runs/real_semantic_38d021e_v1/summary.csv) are saved and
hash-checked. The gateway used real Redis Stack/RediSearch, pinned MiniLM
embeddings, and the pinned NLI answer policy. Generation came from the delayed
deterministic mock provider. Each warm scenario was repeated three times on
the same CI runner and process.

| Scenario | Requests | Cache hits | Mock-provider calls | HTTP errors | HTTP completion p50 / p95 |
|---|---:|---:|---:|---:|---:|
| Exact hit | 3 | 3 | 0 | 0 | 12.360 / 48.306 ms |
| Valid semantic reference match | 3 | 3 | 0 | 0 | 11.884 / 11.990 ms |
| Rejected candidate | 3 | 0 | 3 | 0 | 242.726 / 244.693 ms |
| Cold miss | 3 | 0 | 3 | 0 | 139.945 / 140.780 ms |
| Eight concurrent identical misses × 3 | 24 | 0 | 3 | 0 | 145.731 / 148.285 ms |

Gateway startup to `/health` was **7,535.266 ms**. The first semantic hit,
which lazily loaded NLI, took **7,859.119 ms** end to end and is excluded from
the warm rows. The accepted and rejected examples come from the deliberately
selected NQ diagnostic set: their reference answers are a proxy, not reviewed
truth. Three trials do not establish stable production percentiles, and the
mock-provider timing is not a paid-provider latency estimate.

## Two separate workers

The [two-worker manifest](../evaluation/runs/multiworker_38d021e_v1/manifest.json),
[rows](../evaluation/runs/multiworker_38d021e_v1/requests.csv), and
[summary](../evaluation/runs/multiworker_38d021e_v1/summary.json) use two
independent gateway processes and one shared Redis Stack service. This test
uses exact mode and the delayed mock provider to isolate cross-worker behavior.
The second process hit the first process's same-tenant cache entry. A different
tenant missed. Clearing the first tenant's cache was visible to the second
process. Shared rate and daily-budget limits each returned 429 at their
configured limit; no unexpected HTTP errors were recorded.

For three simultaneous duplicate cold prompts sent one request to each worker,
**each trial made two provider calls**. Process-local coalescing therefore does
not suppress duplicate work across workers. The short mock-provider workload
does not yet justify a distributed lock or lease, which would add failure modes
to the cache path. Measure the rate and cost of real cross-worker duplication
before adding one.

## Real-provider smoke prerequisite

`python -m scripts.smoke_real_provider` is a zero-call preflight. The execute
path tests JSON generation and exact reuse, streaming generation and reuse,
then clears the smoke cache and closes the app. It allows at most two new
requests to one configured real provider. It was exercised with the free mock
provider; **no paid provider call was made**.

To execute against a real provider, provide a disposable `REDIS_URL`, a
configured and verified real provider/model and key, non-demo `API_KEYS`, an
externally enforced account spending cap, and set
`VERIGATE_SMOKE_ACCOUNT_HARD_CAP_CONFIRMED=1` and
`VERIGATE_SMOKE_APPROVED_MAX_USD` to the approved cap. Then run
`python -m scripts.smoke_real_provider --execute --output <new-json-path>`.
The script caps request count and response characters; the provider account cap
must enforce dollars because the gateway does not receive a reliable final
billed-token count from every compatible provider.
