# Controlled-answer HTTP cache stress evaluation

The [frozen 1,000-question workload](../evaluation/runs/nq_song_stress_20261030_v3/workload.csv)
contains 200 song-writer families selected from NQ-Open train, one original, three
authored paraphrase templates, and one authored song-title swap each. NQ-Open is
[CC BY-SA 3.0](https://github.com/google-research-datasets/natural-questions/tree/master/nq_open).
The derived workload retains that attribution and licence. Its reference answer
and source line are recorded on every row. The fixed-answer provider map is
separate from the cache and verifier and is used only after a genuine miss.

These are **authored controls**, not human-reviewed answer labels. NQ short answers
may omit co-writers or aliases. The repeated templates have limited linguistic
diversity; this is not representative production traffic. NQ train also appears
in earlier VeriGate development studies, so this run is not an independent
source-level holdout. The answer-policy artifact and similarity thresholds were
hashed before execution and were not tuned on these results.

The workload was shuffled once with seed 90210. Same-family requests can arrive
before the original. The frozen input hash, model revisions, policy hash,
capacity settings and selection rules are in
[freeze.json](../evaluation/runs/nq_song_stress_20261030_v3/freeze.json).
Every configuration used a fresh evaluation tenant and cache namespace with
real HTTP, Redis Stack, pinned MiniLM, and, for answer-aware mode, pinned NLI.
The normal demo tenant was never accessed. The generic mock provider was not
used, and no paid calls were made.

The [analysis](../evaluation/runs/nq_song_stress_20261030_v3/REPORT.md)
compares exact, static semantic and answer-aware policies with sufficient
capacity and deployment defaults. Request rows include the selected cached
question and answer, reason, threshold, similarity, NLI score when computed,
provider invocation, live-cache opportunity, outcome, and stage/HTTP timings.
See [every suspected wrong acceptance](../evaluation/runs/nq_song_stress_20261030_v3/all_suspected_incorrect_accepts.csv)
and [unnecessary misses](../evaluation/runs/nq_song_stress_20261030_v3/unnecessary_misses.csv).

## Repeat on a machine with Redis Stack and cached pinned models

```powershell
python -m scripts.stress_semantic_http build evaluation/runs/NEW_RUN_ID
python -m scripts.stress_semantic_http run evaluation/runs/NEW_RUN_ID
python -m scripts.analyze_stress_semantic_http evaluation/runs/NEW_RUN_ID
```

The runner starts one local gateway at `127.0.0.1:8767` for each configuration.
It expects Redis Stack at `127.0.0.1:6379`. It uses `HF_HOME` under the
repository's gitignored `.cache/huggingface` and offline model loading. Fresh
model downloads must be arranged separately. It writes progress every 25
requests. An interrupted configuration is retained; a fresh run ID is required
for a full comparison. The earlier `nq_song_stress_20261030_v1` records an exact
run and a model-cache startup failure. The completed v2 run used a static
threshold **plus** the structural verifier; it is retained as an ablation.
The v3 run uses the repository's actual static baseline: fixed 0.72 threshold
without that verifier.
