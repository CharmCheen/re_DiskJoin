# Gate 5B — Step 14: multi-core CPU baseline for the optimized C path (1 / 2 / 4 threads)

Date: 2026-11-03 · Host `amax` (Intel Xeon Silver 4310, 12 physical cores, 2 SMT/core, 1 NUMA node)
Round dir: `workspace/gate5b/runs/step14_cpu_scaling/` (all new artifacts; step7–13 untouched)
Binary: step13-verified C path + a minimal experiment gate (`GATE14_SKIP_BUILD`, see §2).

**Question.** How does the already-integrated **C-path compute loop** scale within **4 physical
cores** on BigANN1M, at 1 / 2 / 4 threads? This is a **CPU-baseline scaling study**, not a GPU claim.

**Bottom line.** The C-path compute loop scales **near-linearly within 4 physical cores**: mean compute
wall **246.84 → 123.15 → 63.47 s** = **2.004× / 3.889×** (parallel efficiency **100.2 % / 97.2 %**),
while the whole-search wall **255.65 → 131.48 → 71.76 s** = 1.944× / **3.563×**, Amdahl-limited by the
~8.1 s **serial preload**. The parallelization is **safe and exact**: the pair multiset is byte-identical
across 1/2/4 threads (100K), and the **exact** distance-call count (`14,090,491,387`) is identical in all
nine 1M runs. No race; no GPU claim; a pure CPU-baseline scaling result.

---

## 1. Parallel-safety audit (requirement 1) — see `PARALLEL_SAFETY_AUDIT.md`

Summarised:

- **OpenMP regions**: taskprep (`DiskJoin.h:79`, static, `GATE4A_KNN_OUT` guarded by `#pragma omp
  critical`) and the join compute region (`DiskJoin.h:377`, `schedule(dynamic)`, reductions
  `+sum +count +dist_comp +g14_dist_exact`); the build in `Kmeans.h` (static/dynamic).
- **Thread control**: **no `num_threads` clause and no `omp_set_num_threads` anywhere**; therefore
  `OMP_NUM_THREADS` is the sole knob and controls **both build and compute**. In step 14 the build is
  skipped, so the compute region is the only remaining variable.
- **Shared buffers**: the only staging buffer shared across phases (`data`) is written **serially** by
  preload and read **read-only** by compute *after the region's implicit barrier*; `Cache` and the
  reader's byte counters are touched only in the serial preload. **No race.**
- **Reductions**: `count` (size_t), `dist_comp` (float), `sum` (unused), `g14_dist_exact` (size_t) are
  all reduction variables — correct.
- **Output sinks are per-thread** (`gate3_count_bufs[tid]`, `gate3_pair_bufs[tid]`); the streaming
  single-thread path is hard-gated to `OMP_NUM_THREADS==1`.
- **C-path temporaries** (`g_v2/g_id/g_d[16]`) are declared inside the loop body ⇒ thread-private.
- **Timing/diagnostics** (`gacc`/`gcpu`, counter prints, invariant checks) run **outside** the
  parallel region ⇒ no double count. Caveat: `gcpu()` is process `clock()`, so it sums threads; it is
  not used as an efficiency numerator.
- **Defect D1 (design, not a race)**: the *build* is nondeterministic across thread counts (parallel
  `graph.addPoint`); see §2.
- **Caveat D2 (pre-existing counter, not a race)**: `dist_comp` is a `float` that saturates; proven by
  an added **exact `size_t` counter** that is **invariant** across threads (100K: 154,113,486 for
  1/2/4 threads; 1M: 14,090,491,387 for 1/2/4 threads).

**Verdict: the compute region is thread-safe; no race found.** Proceed (had the exact counter not
been invariant, the experiment would have stopped).

## 2. Fixed configuration and the build/nondeterminism control (requirement 2)

- Fixed as step 13: **C path** (`GATE13_C_PATH=1`), **BigANN1M**, `radius 73984`, `cluster_num 1000`,
  `K 24`, `error_bound 0.1`, `gt 8379`, `GATE4B0_WINDOW=2`, **10 % cache**
  (`mem_budget 0.0476837158203125`); pair/trace output **OFF** (`GATE3_COUNT_ONLY`).
- **Topology**: 24 logical CPUs = 12 physical cores × 2 SMT, 1 socket, NUMA node 0. CPU *K* and
  *K+12* are siblings. Chosen **nested physical-core sets on node 0**: `1→{2}`, `2→{2,3}`,
  `4→{2,3,4,5}`; binding `taskset -c <set> OMP_PROC_BIND=true OMP_PLACES=cores`, recorded with
  `OMP_DISPLAY_AFFINITY=TRUE` (2 threads → CPUs 2,3; 4 threads → CPUs 2,3,4,5). No server config
  changed; 4 physical cores were available.
- **Build vs compute recorded separately.** The build is **not deterministic across thread counts**
  (measured below), so a per-run rebuild would change the graph between thread versions. To isolate
  the compute loop, step 14 adds a minimal env gate:

  ```c++
  void build(ConfigReader config) {
      if (getenv("GATE14_SKIP_BUILD")) return;   // [GATE14] reuse a fixed verified graph
      one_level_kmeans(config);
  }
  ```

  Patch: `inputs/DiskJoin_GATE14_SKIP_BUILD_AND_EXACT.patch`. All thread configs **reuse one fixed,
  verified graph**: step13's 1M graph (hashes `8f688ef1…`/`86827ea7…`/`eb0be0ed…`) for perf, and
  step2's 100K graph for correctness. Verified a fresh **1-thread** 100K rebuild is **byte-identical**
  to the step2 reference graph. Build threads recorded: **1 thread** (step13/step7; reproduced
  exactly here).
- **Determinism evidence**: 100K build at 1 thread vs 4 threads produced **different** graphs
  (`6bfbf4ef…` vs `2fb63ef5…`); all step14 runs instead share one task hash per dataset
  (100K tasks `4281c529…`, 1M task_total `12449`).

## 3. Correctness (requirement 3)

### 3.1 100K exact set/multiset comparison (1/2/4 threads)
Because multithreaded output **order** changes, every output is compared as an **exact multiset**
(sorted lines, sha256), not by totals.

Reference: frozen step2 100K normal output. Sorted-reference sha256
`e57f9e5da5b35fc38bc40802c8a26de024a125535706294d54fe61be64ebc54c`.

| run | threads | affinity | pairs | sampled_count | exact dist calls | float `dist_comp` | sorted-pairs sha256 | vs ref multiset |
|---|---:|---|---:|---:|---:|---:|---|---|
| t1 | 1 | cpu 2 | 3,855,811 | 2 | 154,113,486 | 154,113,552 | `e57f9e5d…` | **IDENTICAL** |
| t2 | 2 | cpu 2,3 | 3,855,811 | 2 | 154,113,486 | 154,113,552 | `e57f9e5d…` | **IDENTICAL** |
| t4 | 4 | cpu 2,3,4,5 | 3,855,811 | 2 | 154,113,486 | 154,113,552 | `e57f9e5d…` | **IDENTICAL** |

- **Exact pair multiset is identical across 1/2/4 threads and identical to the step2 reference**
  (bit-for-bit after `LC_ALL=C sort`). `pairs` and `sampled_count` match; task dumps share one hash
  `4281c529…`; `gate3-inv` invariants (`task_total=13011`, `bucket_sum=100000`, `upper_triangle_ok=1`)
  match.
- The **exact** `size_t` distance-call counter is **invariant** (`154,113,486`), proving the earlier
  thread-dependent `dist_comp` was only the `float` counter saturating (audit D2) — **not a race**.
- No sanitizer/error strings; all runs rc=0.

### 3.2 1M consistency (counts only — the full 1M output set is NOT re-verified here)
Perf runs are pair/trace-OFF; every run must report `pairs=398,737,742`, `sampled_count=7165`,
`recall=0.855114`, identical cache/IO stats, and an identical **exact** distance count. These are a
**consistency check only**; the 1M output set is verified in step 13, not here.

## 4. Performance (requirement 4)

1/2/4 threads × 3 runs, rotation **1/2/4, 2/4/1, 4/1/2**, same timing for all runs (`GATE5B_PROFILE`
phase wall/CPU + `/usr/bin/time -v` process wall, peak RSS, CPU%). No concurrent timing; the
denominator is **this round's C single-thread** mean.

Per-run data (all nine runs rc=0; `compute_c`/`search_c` are process CPU from `GATE5B_PROFILE`;
`elapsed`, `CPU%`, `RSS` from `/usr/bin/time -v`; `exact` = integer distance calls; `dist_f` = the
saturating float counter):

| run | thr | cpus | compute_w | compute_c | search_w | search_c | preload_w | taskprep_w | elapsed | CPU% | RSS_MB | exact | float dist_comp | sampled | pairs | eff_GB | cache_slots |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r1_t1 | 1 | 2 | 248.596 | 248.576 | 257.469 | 250.585 | 8.406 | 0.425 | 257.47 | 97 | 86.2 | 14090491387 | 10701217792 | 7165 | 398737742 | 2.467 | 39 |
| r6_t1 | 1 | 2 | 245.823 | 245.808 | 254.630 | 247.753 | 8.492 | 0.290 | 254.63 | 97 | 86.2 | 14090491387 | 10701217792 | 7165 | 398737742 | 2.467 | 39 |
| r8_t1 | 1 | 2 | 246.104 | 246.088 | 254.847 | 248.009 | 8.426 | 0.291 | 254.85 | 97 | 86.2 | 14090491387 | 10701217792 | 7165 | 398737742 | 2.467 | 39 |
| r2_t2 | 2 | 2,3 | 123.214 | 246.088 | 131.595 | 251.622 | 8.103 | 0.230 | 131.60 | 191 | 85.9 | 14090491387 | 13317079040 | 7165 | 398737742 | 2.467 | 39 |
| r4_t2 | 2 | 2,3 | 122.674 | 245.020 | 130.964 | 250.420 | 8.101 | 0.161 | 130.97 | 191 | 86.1 | 14090491387 | 13317075968 | 7165 | 398737742 | 2.467 | 39 |
| r9_t2 | 2 | 2,3 | 123.553 | 246.755 | 131.886 | 252.254 | 8.057 | 0.227 | 131.89 | 191 | 85.9 | 14090491387 | 13317082112 | 7165 | 398737742 | 2.467 | 39 |
| r3_t4 | 4 | 2,3,4,5 | 63.733 | 253.931 | 71.993 | 267.418 | 8.095 | 0.122 | 72.00 | 371 | 85.9 | 14090491387 | 14021633024 | 7165 | 398737742 | 2.467 | 39 |
| r5_t4 | 4 | 2,3,4,5 | 62.806 | 250.200 | 71.102 | 263.504 | 8.132 | 0.120 | 71.11 | 370 | 85.9 | 14090491387 | 14021642240 | 7165 | 398737742 | 2.467 | 39 |
| r7_t4 | 4 | 2,3,4,5 | 63.883 | 254.475 | 72.175 | 268.051 | 8.130 | 0.121 | 72.18 | 371 | 85.9 | 14090491387 | 14016656384 | 7165 | 398737742 | 2.467 | 39 |

Means per thread count. **Denominator = this round's C single-thread mean** (never an old runtime).
Time-reduction % and speed-up are different quantities and are kept separate.

| thr | compute_w (s) | search_w (s) | elapsed (s) | speed-up compute | efficiency compute | speed-up search | efficiency search | speed-up process | efficiency process |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 246.841 | 255.649 | 255.65 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 2 | 123.147 | 131.482 | 131.49 | **2.004** | **1.002** | 1.944 | 0.972 | 1.944 | 0.972 |
| 4 | 63.474 | 71.757 | 71.76 | **3.889** | **0.972** | **3.563** | 0.891 | 3.562 | 0.891 |

Equivalent **time reductions**: compute **−50.1 %** (2 thr) and **−74.3 %** (4 thr); search **−48.6 %**
and **−71.9 %**; process **−48.6 %** and **−71.9 %**.

Counts: `pairs=398,737,742`, `sampled_count=7165`, `recall=0.855114`, `capacity_slots=39`,
`effective_bytes=2,466,615,808`, `read_calls=4670` — **identical in all nine runs**; **exact** distance
count `14,090,491,387` **identical in all nine runs**. No sanitizer/error strings.

### 4.1 Scaling reading

- **The compute loop scales essentially linearly to 4 physical cores.** 246.84 → 123.15 → 63.47 s,
  i.e. **2.004×** (efficiency **100.2 %**) and **3.889×** (efficiency **97.2 %**). Using `schedule(dynamic)`
  (chunk 1) over ~1000 per-cluster regions gives near-ideal load balance; the sub-2 % shortfall at 4
  threads is small.
- **End-to-end search/process scaling is Amdahl-limited by the serial preload.** Search
  255.65 → 71.76 s = **3.563×** (efficiency 0.891), not 3.9×. The gap is explained directly by the
  non-compute floor: at 1 thread, `search = preload 8.44 + taskprep 0.34 + compute 246.84`; the serial
  preload is 3.4 % of search. Amdahl (serial 3.4 %, compute 96.6 % at 3.889×) predicts
  `1/(0.034 + 0.966/3.889) = 3.54×` — **measured 3.56×**, i.e. the whole-search result is exactly what
  the compute scaling plus the fixed serial preload predicts. No unexplained loss.
- **Direct evidence of the bottleneck(s):**
  - *Sync / scheduling overhead:* total thread CPU (`compute_c`) is ~flat across thread counts
    (246–254 s) and rises only ~2–3 % at 4 threads → fork/join + dynamic scheduling + worker spin are
    small, not a scaling killer.
  - *Load imbalance:* **not** the limit — dynamic chunk-1 scheduling plus 97 % efficiency shows the
    ~1000 regions are well balanced.
  - *Serial sections:* the ~8.1 s preload (find/read/push), plus serial setup/taskprep/Gorder, are the
    only strong limiters, and they are exactly the Amdahl serial fraction.
- **Not separable / unknown.** Whether the residual ~2.8 % compute shortfall at 4 cores comes from
  shared memory bandwidth, reduced turbo with 4 active cores, or per-region fork/join cost **cannot be
  separated** here: `perf` is unavailable (`perf_event_paranoid=4`) and the process-CPU counter is a sum
  over threads. Marked **unknown**. Likewise the 2-thread efficiency of 100.2 % is within run-to-run
  noise (±0.5 %) rather than a genuine super-linear effect.
- The 8.1 s preload and cache/IO statistics (`read_calls=4670`, `effective_bytes=2,466,615,808`,
  `capacity_slots=39`) are **identical** at all thread counts — the preload is serial and unaffected, so
  the scaling is a pure compute-region effect (not fewer I/Os).
- **GPU benefit is NOT inferred from this thread scaling.** This is a CPU-baseline scaling result only.

## 5. Conclusion (requirement 5)

1. **Within 4 physical cores the C-path compute loop scales near-linearly**: compute wall 246.84 →
   123.15 → 63.47 s = **2.004× / 3.889×** (parallel efficiency **100.2 % / 97.2 %**). This is the direct
   answer to "how does the compute loop scale within 4 cores": very well, with no sign of a
   synchronization or load-imbalance wall.
2. **End-to-end search/process** scales 255.65 → 131.48 → 71.76 s = 1.944× / **3.563×**; the shortfall
   from 3.9× is fully accounted for by the fixed **serial preload** (~8.1 s, 3.4 % of search). The
   measured 3.563× matches the Amdahl prediction (3.54×) built from the measured compute speed-up.
3. **Correctness is preserved under threads.** 100K: the emitted pairs form a **byte-identical multiset**
   across 1/2/4 threads and equal to the frozen step2 output. 1M: `pairs`, `sampled_count`, `recall`,
   cache/IO stats, and the **exact integer distance count (14,090,491,387)** are identical in all nine
   runs. The compute region is thread-safe (audit: no race).
4. **Two non-race issues were found, controlled and reported.** (D1) the *build* is nondeterministic
   across thread counts → isolated with `GATE14_SKIP_BUILD` + one fixed verified graph, so build
   changes are **not** attributed to the compute gain (build was a separate 1-thread step). (D2) the
   pre-existing `float dist_comp` saturates and is thread-partition dependent — proven to be a counter
   artifact, not a race, by the invariant exact `size_t` counter.
5. **Separable vs unknown.** The compute speed-up, the serial preload share, and the Amdahl match are
   directly evidenced. The remaining ~2.8 % sub-linearity at 4 cores is **not separable** into
   bandwidth / turbo / fork-join without `perf` (unavailable) and is marked **unknown**.
6. **Positioning.** This is a **CPU multi-core baseline** for the optimized C path. It makes **no GPU
   claim** and does not infer GPU benefit from thread scaling. Scope: fixed config (`d=128`, 10 % cache,
   BigANN1M, this host), 1/2/4 physical cores.

## 6. Resources
- Wall: **17:25:56 → 17:57:54 ≈ 32 min** (cap 45 min). CPU: ≤ 4 physical cores, pinned; no server change.
- Peak RSS per run: **≈ 86 MB** (`/usr/bin/time -v`, 85.9–86.2 MB) (cap 4 GiB process tree).
  New disk: **0.397 GiB** (`runs/step14_cpu_scaling/`) (cap 2 GiB).
- No download, no install, no GPU, no commit/push/reset/clean; old assets untouched (step7–13 mtimes
  unchanged; git HEAD `ae56a37`).

## 7. Deliverables
- `PARALLEL_SAFETY_AUDIT.md` (this round's audit).
- `inputs/DiskJoin_GATE14_SKIP_BUILD_AND_EXACT.patch` (+ pre-image, source hashes).
- `tools/{run_100k_correctness.sh, run_perf_1m.sh, summarize_perf.py}`.
- `build/main` (Release, step13 C path + GATE14 gates).
- `correctness_100k/t{1,2,4}/` (pairs, sorted multisets, tasks, logs, configs).
- `perf/r1..r9/` (9 runs, per-run stdout/stderr/config/rc), `logs/perf_summary.txt`, `logs/driver.log`.
