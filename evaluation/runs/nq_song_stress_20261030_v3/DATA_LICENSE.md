# Dataset attribution and changes

`workload.csv` and `provider_answers.json` are derived from
[NQ-Open train](https://github.com/google-research-datasets/natural-questions/blob/master/nq_open/README.md),
which the dataset maintainers release under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
The source README asks users to cite Kwiatkowski et al. (2019) and Lee et al.
(2019). The source question and short answer line numbers are recorded in
`workload.csv`; the exact source file hash is in `freeze.json`.

VeriGate selected 200 song-writer questions, changed casing and punctuation,
authored three question templates per source, swapped one song title per family
to make a hard negative, and shuffled the request order. These derived data
files are shared under CC BY-SA 3.0. The implementation code has separate
project terms; this notice applies to the derived data files.
