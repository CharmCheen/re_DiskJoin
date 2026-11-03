# Gate 5B — Step 11: CPU hotspot & phase-timing profile (BigANN1M, normal safe-prefetch)

Date: 2026-11-03 · Host: `amax` · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`
Round dir: `workspace/gate5b/runs/step11_hotspot_profile/` (all new artifacts; prior evidence untouched)

**Question:** is distance computation the main bottleneck of the join? Reuses the **step10 10 %-cache fixed
configuration** (normal safe-prefetch, threshold 73984, single thread, CPU affinity, fixed graph & task order,
pair/trace output OFF, existing counters ON). The algorithm, threshold, sample and data layout are unchanged.

**Bottom line:** yes — **distance computation dominates** (≈96.8 % of the search phase, ≈91.9 % of the whole
process wall time); cache management and read waiting are each **< 3 %** and are *not* bottlenecks. The actual
kernel is **AVX-512F FMA (`L2SqrFloatAVX512`)** reached through an **out-of-line indirect call**.

---

## 0. Executive summary

| hypothesis | verdict | evidence |
|---|---|---|
| **distance-dominated** | **SUPPORTED** | `compute` = **276.91 s = 96.83 %** of search (91.88 % of process wall) |
| **cache-management overhead significant** | **REJECTED** | `find+push` = 0.93 s = **0.33 %** of search |
| **read waiting significant** | **REJECTED (measurable, small)** | `read` = 7.79 s = **2.73 %** of search, of which **7.10 s idle** (blocking O_DIRECT) = 2.48 % |

Ideal end-to-end upper bounds if the measured part were accelerated (Amdahl; **ignores all accelerator
overhead**, see §6): **2× → 1.85×**, **10× → 5.78×** end-to-end.

**perf was unavailable** (permission-denied; §2), so there is **no instruction/cycle/cache-miss/stack
sampling**. This is a *tool/permission* limitation and is **not** evidence that there is no CPU hotspot —
the phase timing independently localises the hotspot.

---

## 1. Source audit

### 1.1 Join phases (`lib/DiskJoin.h::search`, main phases)

| phase | source | work |
|---|---|---|
| **meta load** | `cluster_reader.readMetaData()` (l.23) | read metadata (bucket sizes, centroids, assignment) |
| **graph load** | `new hnswlib::HierarchicalNSW(...)` (l.29–35) | load HNSW graph over the 1000 centroids |
| **task prep** | `#pragma omp parallel for` (l.50–91) | per-cluster `knnSearchBaseLayer(i,K)` + angular pruning → `tasks[]` |
| **Gorder** | `order_gorder(shuffled_tasks, window)` (l.119) | task-order reordering (window pinned = 2) |
| **join setup** | `Cache cache(budget,length); cache.init(...)` (l.239–240) | cache buffer alloc + next-use bookkeeping |
| **join — preload** | l.298–304 | per target cluster: `cache.find` → miss → `posixDirectReadCluster` (O_DIRECT) → `cache.push` |
| **join — compute** | l.307–339 (`#pragma omp parallel for reduction(+:dist_comp)`) | **the distance/pruning loop** |
| **result** | l.341–389 | recall print, counters, gated dumps |

The `build` phase (`one_level_kmeans`, k-means) runs before `search` and is timed separately by `main.cpp`.

### 1.2 `dist_comp` — exact increment sites and coverage

`dist_comp` (a `float`, printed as `[gate3-stat] dist_comp=…`) is incremented at exactly **two** sites, each
immediately after a **point–point** `dist_l2` call:

- `lib/DiskJoin.h:350–351` — same-bucket upper-triangle loop: `dist = dist_l2(vec1, vec2, &d); dist_comp++;`
- `lib/DiskJoin.h:365–366` — cross-bucket loop: `dist1 = dist_l2(vec1, vec2, &d); dist_comp++;`

**Not counted:** the **point-to-centroid** call `dist_l2(vec1, centroids + neighbor_cluster*d, &d)` (l.361),
executed once per (point, neighbour bucket). Count ≈ `Σ_i bucket_size_i · (tasks_i − 1)` ≈ 1e6·(12.4−1) ≈
**~1.1e7** calls vs the **10,701,217,792** counted point–point calls ⇒ **≈0.1 %**, negligible, and it runs
inside the same `compute` region anyway. So `dist_comp` is an accurate proxy for the distance work executed.

### 1.3 The *actual* enabled distance kernel (source + compiled binary)

Call path: `dist_l2` is a **global function pointer** (`auto dist_l2 = utils::L2Sqr;`, `lib/ClusterIO.h:20`,
symbol `D dist_l2`) → `utils::L2Sqr` (`utils/dist_func.h:612`) → `L2SqrSIMD` (`:475`) →
`L2SqrFloatAVX512`. The `L2Sqr` guard is

```c
#if defined(USE_AVX512) || defined(USE_AVX512) || defined(USE_SSE)   // NOTE: USE_AVX512 twice; USE_AVX never tested
    res = L2SqrSIMD(...);
#elif                                                                 // (empty #elif — latent portability bug)
```

`USE_SSE/USE_AVX/USE_AVX512` are defined in `lib/hnswlib/hnswlib.h:1–11` from `__SSE__/__AVX__/__AVX512F__`.
The CMake flags **do not** set `-DUSE_AVX512` (only `-DUSE_AVX2`), **but** the flags end with `-march=native`,
which defines `__AVX512F__` on this host, so `USE_AVX512` **is** defined.

**Determined from the compiled instructions, not from `/proc/cpuinfo`:** `objdump` of `utils::L2Sqr` in the
step11 binary shows the AVX-512F FMA kernel (`vmovups/vsubps/vfmadd231ps` on **`zmm`** registers), 16 distinct
zmm registers, 114 `vfmadd*ps` in the binary. ⇒ **the join distance kernel is `L2SqrFloatAVX512`**.

**Important micro-architectural note:** because `dist_l2` is a *mutable global function pointer*, each call is
an **indirect call** and `utils::L2Sqr` is an **out-of-line** symbol (`t`, not inlined); the AVX-512 body is
reached only after a prologue + dimension-dispatch. At `dist_comp = 10.70e9` calls and `compute = 276.91 s`,
that is **≈25.9 ns/call**, which includes per-call call/branch overhead *in addition to* the 8 zmm FMA groups
for `d=128`. Raw evidence: `logs/kernel_determination.txt`.

---

## 2. Low-overhead CPU sampling — **perf unavailable (recorded), fallback used**

Probe (no install, no settings change), saved in `logs/perf_probe.log`:

- `/usr/bin/perf` exists (`perf version 6.8.12`), but `/proc/sys/kernel/perf_event_paranoid = 4` and the
  process has **no** `CAP_PERFMON`/`CAP_SYS_PTRACE`/`CAP_SYS_ADMIN` (`CapEff = 0`).
- `perf stat -e task-clock,cycles,instructions -- true` → *"Access to performance monitoring and
  observability operations is limited."* (denied). `perf record` → same denial.

⇒ **No sampling run was performed.** Consequently there are **no** available events (no task-clock, cycles,
instructions, cache-misses, page-faults, context-switches), no call stacks, and **no instruction/cycle
attribution** — so the AVX-512 kernel body cannot be separated from the indirect-call overhead, and there are
no per-function proportions. **This is a permission/tool limitation, NOT a finding that no CPU hotspot
exists.** The hotspot is instead located by the coarse phase timing below.

*(The `/usr/bin/time -v` figures in stderr.log are OS counters from the timed run — not hardware PMU events:
Minor faults 40317, Voluntary ctx switches 12585, Involuntary 1976, User 293.34 s, Sys 0.91 s.)*

---

## 3. Coarse phase timing (one run, fixed config)

Minimal env-gated patch `GATE5B_PROFILE` (see §4). **Coarse boundaries only**: one timer pair per phase, per
cluster (`preload` vs `compute`) and per cache-access type; **never per distance call**. Wall (`steady_clock`)
and process-CPU (`clock()`) are recorded separately; the wall−CPU difference isolates blocking waits. Slots are
non-overlapping except that `find/read/push` **nest inside** `preload`, and `SEARCH_TOTAL` encloses all —
reporting nests them but they are **never summed across nest levels**.

### 3.1 Phase table (single run `runs/profile_10pct`, rc=0)

| phase (exclusive) | wall_s | cpu_s | % of search | wall−cpu (idle) |
|---|---:|---:|---:|---:|
| meta | 0.0027 | 0.0027 | 0.001 % | ~0 |
| graph | 0.0016 | 0.0016 | 0.001 % | ~0 |
| taskprep | 0.2915 | 0.2915 | 0.102 % | ~0 |
| setup | 0.00004 | 0.00004 | ~0 | ~0 |
| gorder | 0.0031 | 0.0031 | 0.001 % | ~0 |
| join_setup | 0.0132 | 0.0132 | 0.005 % | ~0 |
| **preload** | **8.7459** | 1.6450 | **3.058 %** | **7.1009** |
| ├ find | 0.6552 | 0.6566 | 0.229 % | ~0 |
| ├ **read** | **7.7940** | 0.6968 | **2.725 %** | **7.0972** |
| └ push | 0.2729 | 0.2732 | 0.095 % | ~0 |
| **compute** | **276.9144** | 276.8887 | **96.832 %** | 0.0256 |
| result | 0.00005 | 0.00005 | ~0 | ~0 |
| **SUM (exclusive)** | **285.9725** | 278.8460 | **99.999 %** | |
| **SEARCH_TOTAL** | **285.9747** | 278.8474 | 100 % | 7.1272 |

**Timing coverage:** the sum of exclusive slots covers **99.999 %** of `SEARCH_TOTAL` (untimed gap
0.0021 s). `SEARCH_TOTAL` (= `search()`) = **285.975 s**; adding the `build` phase (main's
`[15.400 s] Build done`) gives the process wall **301.375 s**, matching `/usr/bin/time` elapsed **301.38 s**
and the printed `[301.379 s] Join done`.

> Note on `main.cpp`: `Timer::tuck` does **not** reset the start point, so the printed `[X s] Join done` is
> **cumulative (build+search)**. The search phase itself is **285.98 s**, not 301.38 s.

### 3.2 What each result means

- **`compute` = 276.91 s (96.83 %)** is the `#pragma omp parallel for` region containing the **10.70e9
  `dist_l2` calls**, the `dist < epsilon²` prune test, the pair counters and the (count-only) result sink.
  Its wall−CPU gap is only **0.026 s** ⇒ the distance loop is **almost pure CPU-bound**. At this granularity
  the AVX-512 kernel body, the indirect-call overhead, the loop and the result handling are **inseparable** —
  I do not claim a finer split without PMU/instruction counts.
- **`preload` = 8.75 s (3.06 %)**, of which **`read` = 7.79 s** is the only materially idle part
  (**7.10 s** blocked in `read(2)` on `O_DIRECT`; effective bandwidth ≈ 2.47 GB / 7.79 s ≈ **317 MB/s**,
  4670 reads of ~512 KB). Because the preload is a **serial** loop (not overlapped with compute), this wait is
  **fully exposed** wall time.
- **cache management** (`find` 0.66 s + `push` 0.27 s = **0.93 s, 0.33 %**) — hash lookup + heap updates +
  `memcpy` of buckets — is **negligible**.
- All other phases (meta, graph, task prep, Gorder, join setup, result) total **< 0.32 s (< 0.11 %)**.

---

## 4. Minimal patch (and scope)

- File (before → after): `instrumented/DiskJoin/lib/DiskJoin.h` (`5e597bb6…` → `0cb06fb9…`).
- Patch: `inputs/DiskJoin_GATE5B_PROFILE.patch` (pre-image saved as `inputs/DiskJoin.h.before`).
- Gate: `GATE5B_PROFILE` (unset → reference behaviour). Adds `<chrono>`/`<ctime>`, a local timer helper, and
  coarse timers around: meta / graph / taskprep / setup / gorder / join_setup / (per-cluster) preload+find+
  read+push / compute / result, plus a final `[gate5b-prof]` print. **No algorithm, threshold, ordering,
  sample, data-layout or counter change.** The only refactor in the hot path is
  `if(!cache.find(...)){...}` → `bool f=cache.find(...); gacc(...); if(!f){...}` (same single `find` call,
  identical side effects). Adds ≈22 k timer pairs total (negligible).

**Counts match step10 exactly** (so the patch did not perturb the join): `dist_comp = 10,701,217,792`,
`emitted_pairs = 398,737,742`, `sampled_count = 7,165`, `gt = 8,379`, `recall = 0.855114`, cache
`capacity_slots=39 hit=7779 miss=4670 admit=39 evict=3210 reject=1421`, `read_calls=4670`,
`effective_bytes=2,466,615,808`, `task_total=12449`. Graph (`8f688ef1…` / `86827ea7…` / `eb0be0ed…`) and
task-order (`d699f722…`) hashes are **byte-identical to step7/step10**. Config differs from step10 `r02_b010`
**only** in the graph directory path (a fresh dir, so step10's evidential graph was not overwritten). See
`logs/step10_consistency.txt`.

---

## 5. Hypothesis tests

1. **"distance computation dominates" → SUPPORTED.** `compute` = **96.83 %** of search, **91.88 %** of the
   process wall. It is CPU-bound (wall−CPU = 0.026 s) and contains the 10.70e9 distance calls.
2. **"cache-management overhead is significant" → REJECTED.** `find+push` = **0.33 %** of search (0.93 s).
   The Belady heap and bucket `memcpy` are not a hotspot.
3. **"read waiting is significant" → REJECTED as a bottleneck** (but real): `read` = 2.73 % of search, of
   which **7.10 s** is genuine idle device wait (2.48 % of search / 2.36 % of process). It is the *only*
   non-compute exposure of note; its elimination is bounded by ≤ ~2.4 % end-to-end.

---

## 6. Ideal end-to-end upper bounds (Amdahl) — and what they are **not**

Baseline process wall = **301.375 s**. Accelerating a *fraction f* of it by *s×* gives
`T = 301.375 − part·(1 − 1/s)`. These bounds assume the accelerated part becomes ~free and **nothing else
slows down**; they **ignore all extra overhead** (data movement, launch, sync, lower efficiency on another
engine).

| accelerated part (measured) | 2× | 10× | ∞ (part → 0) |
|---|---:|---:|---:|
| **distance compute (276.91 s)** | **162.92 s (1.85×)** | **52.15 s (5.78×)** | 24.46 s (12.32×) |
| whole search (285.97 s) | 158.39 s (1.90×) | 44.00 s (6.85×) | 15.40 s (19.57×) |
| read wait only (7.10 s) | 297.83 s (1.01×) | 294.99 s (1.02×) | 294.28 s (1.02×) |

**Caveat (explicit):** these proportions are **CPU time shares measured on the host**, and a GPU does **not**
inherit the same efficiency — moving the distance loop to a GPU adds host↔device transfer, kernel launch and
synchronisation, and the arithmetic may be efficiency-limited differently. **Do not read the table as a
prediction that a GPU yields these speed-ups.** It only bounds what is *theoretically available* if the
measured part became instant on this machine.

---

## 7. Resources for this round (caps: 20 min wall / ≤4 CPU / Join 1 thread / process RSS ≤4 GiB / new disk ≤1 GiB)

| measure | value | status |
|---|---|---|
| round wall | 16:09:29 → ~16:22 ≈ **13 min** | < 20 min |
| CPU | build `--parallel 4`; Join **96–97 % = 1 thread**, pinned `taskset -c 2` | ≤ 4 CPU |
| process-tree RSS | peak **91,024 KB ≈ 88.9 MiB** | ≪ 4 GiB |
| new disk | `step11_hotspot_profile/` ≈ **499 MB** (graph 498 MB) | < 1 GiB |
| sampling runs | **0** (perf denied) | ≤ 1 |
| phase-timing runs | **1** (`runs/profile_10pct`) | ≤ 1 |
| downloads / GPU / git | none; no commit/push/reset/clean | — |

---

## 8. Deliverables

- `runs/profile_10pct/` — `config`, `stdout.log`, `stderr.log`, `monitor.log`, `hashes.txt`, `gates.txt`,
  `rc.txt`, `phase_profile.tsv`.
- `logs/phase_summary.txt` (phase table + Amdahl), `logs/perf_probe.log`, `logs/kernel_determination.txt`,
  `logs/step10_consistency.txt`, `logs/driver.log`, `logs/{cmake,build}.{out,time}`.
- `inputs/DiskJoin.h.before`, `inputs/DiskJoin_GATE5B_PROFILE.patch`; `build/main` (patched binary).
- `tools/run_profile.sh` (reproduce), `tools/summarize_profile.py`.
- Reproduce: `bash runs/step11_hotspot_profile/tools/run_profile.sh`.

## 9. Limitations

- **No PMU sampling** (perf denied): no cycles/instructions/cache-misses/stacks; per-function proportions and
  the kernel-vs-call-split are not available. The hotspot is localised by *phase* timing only.
- The `compute` figure is the whole parallel-for region (distance calls + prune compare + pair counters +
  count-only sink), not the bare distance arithmetic.
- Single run; build (k-means, 15.4 s) is repeated each run and included in the process wall.
- Wall−CPU for `read` attributes device wait, but the preload is serial, so its 7.10 s is fully exposed.
- Timing overhead ≈22 k timer pairs (< a few ms), consistent with the 99.999 % coverage.
