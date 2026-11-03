# Step 14 — Parallel-safety audit of the DiskJoin C path (multi-core CPU baseline)

Date: 2026-11-03 · Host `amax` (Intel Xeon Silver 4310, 1 socket, 12 physical cores,
2 SMT/core, 1 NUMA node `0-23`) · Cross-reference: `STEP14_CPU_SCALING_REPORT.md`.

Scope: the step13-verified C path (`GATE13_C_PATH`, `lib/gate13_l2.h`) inside
`instrumented/DiskJoin/lib/DiskJoin.h`, audited for correctness under
`OMP_NUM_THREADS ∈ {1,2,4}`. **No source logic was trusted as "thread-safe just
because it did not crash";** every shared mutable object was traced to its
writers/readers and the reductions were checked against the emitted results.

## 1. OpenMP regions actually present

| file | line | region | schedule / clauses |
|---|---|---|---|
| `lib/DiskJoin.h` | 79 | task candidate preparation (`for i < cluster_num`) | static (default); `#pragma omp critical` at :99 guards `GATE4A_KNN_OUT` |
| `lib/DiskJoin.h` | 377 | **join compute** (`for j < bucket_sizes[target_cluster]`) | `schedule(dynamic)` (chunk 1); `reduction(+:sum) reduction(+:count) reduction(+:dist_comp) reduction(+:g14_dist_exact)` |
| `lib/Kmeans.h` | 27,34,51,94,197 | build (k-means / HNSW insert / assignment) | static |
| `lib/Kmeans.h` | 115,129 | build (`add`/`add2choice`) | `schedule(dynamic)` |

**Thread-count control.** There is **no `num_threads(...)` clause and no
`omp_set_num_threads`/`omp_set_dynamic` anywhere** in the tree (verified by
`grep`). Therefore `OMP_NUM_THREADS` is the *only* knob and it governs **both the
build phase and the compute region**. This is the single most important fact for
step 14, and it is also why the build must be decoupled from the experiment
(§4, D1).

Affinity control used in step 14: `taskset -c <nested set>` +
`OMP_PROC_BIND=true OMP_PLACES=cores OMP_DISPLAY_AFFINITY=TRUE`. Recorded
bindings: 2 threads → CPUs `2,3`; 4 threads → CPUs `2,3,4,5` (distinct physical
cores on NUMA node 0; CPU *K* and *K+12* are SMT siblings, so `2/3/4/5` are 4
physical cores).

## 2. Shared state, writer/reader analysis

| object | written by | read by compute region | verdict |
|---|---|---|---|
| `data` (staging buffer, `max_task_num*length`) | serial preload loop only (`posixDirectReadCluster` + `Cache::find` memcpy) | yes, read-only | **safe** — the parallel region has an implicit end barrier; the next preload only starts after all compute iterations finished |
| `Cache` (`address_table`, `ptr`, heap, `data`) | serial preload only | no | **safe** (never touched inside the region) |
| `cluster_reader.reads/used/total` | serial read path only | no | **safe** |
| `assignment`, `bucket_sizes`, `centroids`, `reordered_tasks` | built serially before the loop | yes, read-only | **safe** |
| `count` | OMP reduction `+` | — | **safe** |
| `dist_comp` (float) | OMP reduction `+` | — | reducer is correct; value is approximate, see D2 |
| `sum` (float) | OMP reduction `+` | not used in body | harmless (unused) |
| `g14_dist_exact` (size_t, diagnostic) | OMP reduction `+` | — | **safe**, exact |
| pair sinks | per-thread buffers, see §3 | — | **safe** |
| `graph` (taskprep) | constructed serially; `delete`d after the region | taskprep only | **safe** — `knnSearchBaseLayer` is a read-only traversal and obtains a per-thread `VisitedList` from `VisitedListPool` (mutex-guarded, `visited_list_pool.h:50-68`) |

Compute-body state is either a loop-local (`id1`, `vec1`, `id2`, `dist`, `l`,
`k`, `b`, `g_id`, `g_d`, `gcnt`) or read-only shared data. No shared mutable
scalar without a reduction was found.

## 3. Result handling / sinks / counters

- `gate3_count_bufs[omp_get_thread_num()]` and
  `gate3_pair_bufs[omp_get_thread_num()]` are indexed **per thread** — no
  locking needed and no lost pairs. Sized by `omp_get_max_threads()`.
- The **streaming** pair path (`GATE3_PAIR_STREAM`) is a single-thread-only
  optimization and is **hard-gated**: it `exit(1)`s unless
  `omp_get_max_threads()==1` (`DiskJoin.h:307`). It is **not** used in step 14
  multithreaded runs.
- `count` (sampled) is `size_t`; `pairs` totals are `size_t`; both are exact.
- `recall`, `cache.g4a_stats()`, `[gate4b1-io]`, `[gate3-stat]` all execute
  **after** the serial `for i < cluster_num` loop, single-threaded.

## 4. Timing / diagnostics races

- `gnow()` (steady_clock) and `gcpu()` (process `clock()`) are called **only
  outside** the parallel region: `g_cp_w0` before it, `gacc(...)` after it. The
  region's implicit barrier makes the wall delta exact; there is **no
  double-count** of a concurrent interval.
- `gcpu()` uses process `clock()`, which **sums all threads**. So each phase's
  `cpu_s` is total thread CPU, not wall. During predominantly serial phases the
  idle OpenMP workers can spin, so `cpu_s` there overstates useful work. This is
  a *measurement* note, not a race. It is also why `cpu_s` is not used as a
  parallel-efficiency numerator in the report.
- Diagnostics (`[gate4a-config]`, `[gate3-inv]`, `GATE4A_TASK_OUT`) run in the
  serial setup section. `GATE4A_KNN_OUT` is the only parallel diagnostic and is
  `#pragma omp critical`-guarded.

## 5. C-path temporary buffers

`lib/gate13_l2.h` uses only caller-provided pointers; the per-iteration staging
arrays `g_v2[GATE13_BLK]`, `g_id[GATE13_BLK]`, `g_d[GATE13_BLK]` are declared
**inside the parallel loop body** (`DiskJoin.h` compute region), hence
thread-private automatic storage. The kernel is a pure function of read-only
inputs. **No shared C-path temporary buffer exists.**

## 6. Defects / caveats found

### D1 — build phase is **not deterministic across thread counts** (experiment-design; NOT a memory race)
`one_level_kmeans` builds the HNSW graph with `#pragma omp parallel for` around
`graph.addPoint` (`Kmeans.h:197`). hnswlib inserts with internal locks, so it is
race-*free*, but the resulting link structure depends on the interleaving of
concurrent insertions. **Measured:** a 100K build at `OMP_NUM_THREADS=1` and at
`=4` produce **different** `data.hnsw`, `data.clusters`, `data.metadata`:

```
1 thread : clusters 6bfbf4ef…  metadata a1fe94de…  hnsw 212f0a5f…   (= step2 reference, exact)
4 threads: clusters 2fb63ef5…  metadata 3d7ae20a…  hnsw e62b31cf…
```

Because `OMP_NUM_THREADS` also drives the compute region, a naive "run 1/2/4
threads and rebuild each time" experiment would change graph+tasks between
versions and confound the compute comparison. **Mitigation:** step 14 adds an
env gate `GATE14_SKIP_BUILD` (patch `inputs/DiskJoin_GATE14_SKIP_BUILD_AND_EXACT.patch`)
that skips `one_level_kmeans`; all thread configurations then **reuse one
fixed, verified graph** (`step13` 1M graph, and `step2` 100K graph for
correctness). Verified: a fresh 1-thread 100K rebuild is **byte-identical** to
the step2 reference graph, and all step14 task dumps share one hash.

### D2 — `dist_comp` is a `float` and saturates (pre-existing counter artifact; NOT a race)
`dist_comp` is declared `float` (`DiskJoin.h:289`). A single target cluster can
perform up to ~1.5e8 distance calls, far above `2^24 ≈ 1.7e7`, so the float
accumulator loses low bits; its reduced value therefore depends on the
per-thread partition. At 1M, the C path reports e.g. `10,701,217,792` at 1 thread
vs `14,016,235,520` at 4 threads — while the **true** exact count is
**14,090,491,387** (i.e. the 1-thread float undercounts by ~24 %).
**This is not a data race** — proven by an added **exact `size_t` counter**
(`g14_dist_exact`, incremented at the exact same 4 sites, `GATE14_EXACT_COUNT=1`):

```
100K, exact distance calls: t=1 => 154,113,486 ; t=2 => 154,113,486 ; t=4 => 154,113,486   (invariant)
1M,   exact distance calls: t=1 => 14,090,491,387 ; t=2 => 14,090,491,387 ; t=4 => 14,090,491,387
```

The real product was independently proven identical: the 100K pairs **multiset**
is byte-identical across 1/2/4 threads and equal to the frozen step2 output
(sha256 of sorted pairs `e57f9e5d…`), and `pairs`/`sampled_count`/task hashes are
identical. A race would corrupt the emitted pair set; it does not.

### D3 — `sum` reduction is unused; `dist_comp` float is a latent instrumentation bug
Minor: the `reduction(+:sum)` is never read in the body, and using `float` for a
count is the root of D2. Neither affects join correctness.

## 7. Verdict

The **compute region is thread-safe**: reductions are correct, output sinks are
per-thread, the only shared buffer shared between phases (`data`) is written
serially and read after a barrier, C-path temporaries are loop-local, and all
timers/counters are updated outside the region. **No data race was found.**

The two issues above are (D1) an experiment-design nondeterminism of the *build*
phase and (D2) a pre-existing approximate counter — neither is a defect of the
compute parallelization. Both are controlled/proven, so the step-14 performance
experiment proceeds. If D2's exact counter had **not** been invariant, it would
have indicated a genuine defect and the experiment would have stopped.

**OMP_NUM_THREADS controls the compute region: YES** (no `num_threads` clause,
no `omp_set_num_threads`), and in step 14 the build is skipped so it is the only
remaining variable.
