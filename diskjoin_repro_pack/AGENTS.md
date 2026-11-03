# Agent operating contract — DiskJoin minimal reproduction

## Objective and boundaries

You are a systems-reproduction engineer. Start from `README.md` and `docs/CORE_IDEA.md`.
Deliver a transparent **single-machine minimal reproduction** of DiskJoin, progressing from an offline microexperiment to a correct 12k-vector smoke run, then to mechanism ablations *only with explicit authorization*. Do not silently expand the scope to 10M/100M, use multiple machines, purchase cloud storage, or alter remote system configuration.

## Hard constraints

1. **Preserve upstream code**: `reference/DiskJoin/` is read-only reference material. Pin to SHA `aa86151f97527b1dcf9a032d523c1d67d892454a`; record `git status --short` and `git rev-parse HEAD`. Never run `git reset --hard`, `git clean`, commit, push, force checkout, or overwrite existing uncommitted work.
2. **Isolation**: put generated data, modified experiments, scripts and logs under `workspace/` or a new clearly named `experiments/` directory. Build the pristine repo out-of-tree at `workspace/build`. For changes to upstream, use a new worktree or a copy and generate a patch relative to the frozen SHA.
3. **Safe execution**: do not run the upstream `scripts/run.sh` or `scripts/create_datasets.sh` in the minimum phase. Do not automatically run `sudo`, `apt`, `pip install`, `curl | sh`, large downloads, long jobs, data deletion or permission changes. Explain precise intended resource cost and request authorization before these actions. `scripts/fetch_sources.sh` is a user-initiated opt-in source download, and only downloads the small repository + one PDF.
4. **Facts vs. claims**: distinguish (a) paper claims, (b) directly inspected code, (c) experiment observation, (d) conjecture. Do not claim ACM official artifact status solely from repository similarity.
5. **GT/recall**: `DiskJoin.h` increments its count for vector IDs divisible by `100000` and divides by config `gt`. Thus the printed quantity is sampled recall under its ground-truth convention. On small toy data, only ID 0 is sampled. Never report this as full join Recall without independently enumerating outputs and GT.
6. **Baseline fairness**: keep dataset, epsilon, bucketization, candidate tasks, CPU affinity, memory budget, measurement window and Recall protocol fixed when comparing optimizations. Gorder-off, cache-policy alternatives and pruning-off may require source patches; audit correctness before comparison.
7. **Single-host resource discipline**: default to `OMP_NUM_THREADS=4` and `BUILD_JOBS=4`, check free space and memory first, and do not monopolize a shared server. Avoid GPU use; the upstream code runs on CPU/SSD.
8. **Correct reporting**: a successful CMake build is not experimental reproduction. A successful synthetic smoke test is not reproduction of reported SIGMOD 2026 speedups. Stop and report unexpected crashes, invalid data, missing dependencies, invalid Recall, or O_DIRECT incompatibility.
9. **Source integrity**: DOI `10.1145/3769780` is the PACMMOD Version of Record. arXiv `2508.18494v2` is a separate preprint. Do not relabel either. Keep original PDFs unmodified.
10. **Minimize changes**: inspect code/config/tests before edits. Protect user changes. Report failed/skipped tests, no speculative fixes in the frozen reference repo.

## Sequential gates

**Gate 0: source + environment** — confirm Linux, native AVX2/FMA, compiler, CMake, disk; verify Git SHA; confirm paper availability/version. If unavailable, report blocker.

**Gate 1: insight demo** — `python3 scripts/micro_task_cache.py`, `python3 -m unittest discover -s tests -v`. Report Belady misses for original vs reordered task order. Explicitly mark the demo as pedagogical, not the exact C++ Gorder code.

**Gate 2: toy binary smoke** — invoke `bash scripts/run_smoke.sh`. Confirm n/d, valid config GT, compiled binary, process exit 0, finite `0 <= recall <= 1`, snapshots + logs. Do NOT interpret toy performance as paper performance.

**Gate 3: audit (no new large job)** — read `reference/DiskJoin/lib/{DiskJoin,Gorder,Cache,Kmeans,ClusterIO}.h`, compare with formal paper sections, list mismatches and what would be required for clean ablations and full evaluation.

**Gate 4: ablations (only after explicit user authorization)** — implement and test disabled Gorder, Belady vs LRU, pruning variants and controlled workloads in an isolated copy; add instrumentation. Use exact GT or sufficiently robust sampled GT. Record all changes.

## Required report to user

Provide `workspace/REPORT.md` with: environment; source SHA; paper source; exact commands; data cardinality, dimensions and epsilon; chosen resources; checks/tests and outputs; log paths; failures and hypotheses; validation level (`mechanism`, `smoke`, `mechanism_ablation`, `paper_level`); open blockers; evidence behind all claims; and next Gate.
