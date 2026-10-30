# Live Redis + MiniLM gateway checkpoint

## 30 October prewarm and repeated path check

The [new manifest](../evaluation/runs/prewarm_semantic_8d79c81_v1/manifest.json),
[request rows](../evaluation/runs/prewarm_semantic_8d79c81_v1/requests.csv), and
[summary](../evaluation/runs/prewarm_semantic_8d79c81_v1/summary.csv) came from
[CI run 41002074179](https://github.com/ABHISHEK27Y/VeriGate/actions/runs/41002074179)
at commit `8d79c81`. Two gateway processes ran sequentially on one GitHub runner
against Redis Stack, pinned MiniLM and NLI, and a delayed deterministic mock
provider. Each warm scenario has 30 observations per mode. This is descriptive
single-runner timing, not a production latency distribution.

| Scenario | Lazy p50 / p95 | Prewarm p50 / p95 | Provider calls in each mode | NLI inference calls in each mode |
|---|---:|---:|---:|---:|
| First semantic NLI hit (one observation) | 1,334.897 / 1,334.897 ms | 59.196 / 59.196 ms | 0 | 1 |
| Same-query hit in semantic mode (30 trials) | 12.648 / 19.735 ms | 12.540 / 19.201 ms | 0 | 1 |
| Valid semantic reference hit (30 trials) | 12.418 / 17.251 ms | 12.296 / 14.601 ms | 0 | 0 |
| Answer-mentioned candidate sent to provider (30 trials) | 248.141 / 252.138 ms | 247.514 / 249.161 ms | 30 | 0 |
| Cold miss (30 trials) | 164.049 / 169.511 ms | 164.183 / 168.212 ms | 30 | 0 |
| Eight simultaneous identical misses | 160.423 / 161.447 ms | 151.702 / 152.502 ms | 1 | 0 |

The same-query hit is in **semantic mode**, so it reaches the answer policy; one
new assertion pair invoked NLI on the first warm trial and later trials used the
verifier's pair cache. The 30 valid semantic trials likewise reused a previously
scored pair. The answer-mentioned guard declined all 30 selected candidates
before NLI. All 258 HTTP rows returned 200. The source queries are selected NQ
diagnostic references, not independently reviewed answer-quality labels.

Gateway startup to `/health` was 5,031.857 ms with lazy NLI and 6,025.790 ms
with required prewarm. Prewarm spent 1,209.471 ms loading the NLI model during
startup. In the lazy first request, NLI model load took 1,253.493 ms and NLI
inference 65.333 ms; in the prewarmed first request, inference took 44.362 ms.
Startup plus first request was 6,366.754 ms lazy versus 6,084.986 ms prewarmed
in this one sequential comparison. This does not establish a total speedup;
prewarm primarily moves work before readiness. The earlier 7.859 s cold request
included a different runner's download/load conditions and is preserved below.

Enable only for the optional semantic answer policy:

```powershell
$env:CACHE_MATCH_MODE = "semantic"
$env:ANSWER_POLICY_ARTIFACT = "app/cache/artifacts/answer_policy_v1.json"
$env:ANSWER_POLICY_PREWARM = "true"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The app becomes ready after model initialization succeeds. Leave
`ANSWER_POLICY_PREWARM=false` for the default lazy behavior; exact matching
remains the gateway default.

## Earlier live checkpoint

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
