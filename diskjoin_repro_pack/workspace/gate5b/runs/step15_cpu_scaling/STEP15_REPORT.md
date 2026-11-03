# Gate 5B — Step 15: 1M 4-thread correctness + frozen CPU baseline

Date: 2026-11-03 · Host `amax` (Intel Xeon Silver 4310, 12 physical cores, 2 SMT/core, 1 NUMA node)
Round dir: `workspace/gate5b/runs/step15_cpu_scaling/` (all new artifacts; steps 2,7–14 untouched)
Binary: step13-verified C path + an **output-only** per-thread streaming sink (new `GATE15` gate).

**Scope.** This round does **not** run a new performance experiment. It (1) writes an erratum for the
`dist_comp` distance counter, (2) completes the **full 1M 4-thread exact-multiset correctness check**
against the single-thread reference, and (3) freezes the CPU baseline as
`CPU_BASELINE_MANIFEST.json`. Hard caps: 30 min wall, ≤4 CPU, process-tree RSS ≤2 GiB, ≤16 GiB new
disk. No download, no GPU, no commit/push/reset/clean.

**Bottom line.** The 1M 4-thread join emits a pair multiset that is **exactly identical** to the
step7 single-thread reference: after `LC_ALL=C` sort, both streams have SHA256
`863affa8…`, `N = U = 398,737,742`, `duplicates = 0`, all sort/aggregation exit codes 0. The exact
`size_t` distance-call count is `14,090,491,387` (invariant). Peak RSS was **102 MB**; wall
**88.3 s**. The CPU baseline is frozen with three named configurations and separated evidence scopes.

---

## 1. Erratum — `dist_comp` is a saturating `float`

Full text: `erratum/STEP15_DIST_COMP_ERRATUM.md`. Summary:

- **Type / sites / reduction.** Old `float dist_comp` (binary32) and new exact `size_t
  g14_dist_exact` (8 bytes here) are both `reduction(+:…)` on the same
  `#pragma omp parallel for schedule(dynamic)` (source line 377), incremented at the same 2 logical
  sites (same-bucket and cross-bucket point–point loops; textual lines 406/435 C-path, 450/465
  original path). The point-to-centroid call is uncounted (~1.1e7, ≈0.078 % of the exact count).
- **Old vs new.**

  | dataset / threads | old `dist_comp` (float) | new exact (`size_t`) | Δ |
  |---|---|---:|---:|
  | 1M / 1 thread | 10,701,217,792 | 14,090,491,387 | **−24.05 %** |
  | 1M / 2 threads | ≈13,317,07x,xxx | 14,090,491,387 | ≈−5.49 % |
  | 1M / 4 threads | ≈14,0xx,xxx,xxx | 14,090,491,387 | ≈−0.49 % |
  | 100K / any | 154,113,552 | 154,113,486 | +66 |

- **Reason.** `float` cannot represent every integer above 2^24 = 16,777,216, so `dist_comp++`
  stalls/rounds inside large per-thread reductions. 1 thread puts a whole large cluster on one thread
  (severe under-count); 4 threads split it (small rounding). At 100K per-region totals stay below
  2^24, leaving only thread-invariant outer-accumulation error.
- **Affected historical conclusions** (count/rate-derived only): step10's "10,701,217,792 distance
  computations"; step11 §1.2 "accurate proxy" (false), §1.3 "25.9 ns/call" (**→ 19.65 ns/call**),
  §4/§5 counts (**→ 14.09e9**); step7/8/9 consistency tokens; step13 counters; REPORT.md
  "154 M → ~15 G" (**→ ≈91×, "~14 G"**). step11 §6 Amdahl and all wall/CPU-time conclusions are
  **unaffected** (time-based, not count-based). step12's replay counter and step14's exact counter are
  already correct.
- **Recommendation.** Count with explicit-width `uint64_t` (64-bit required: 1.4e10 > 2^32) and format
  explicitly (`std::to_string`/`PRIu64`), never `(size_t)`-cast a `float`.
- Old reports and all measured timings/outputs were **not modified**; this is an added document.

---

## 2. Full 1M 4-thread correctness (exact multiset)

### 2.1 Method

- **Compute path:** `GATE13_C_PATH=1` (the step12/13 optimized C path) — unchanged.
- **Fixed graph/tasks/config:** `GATE14_SKIP_BUILD=1` reuses the step13 1M graph
  (`8f688ef1…` / `86827ea7…` / `eb0be0ed…`), task order `d699f722…`; config exactly the step13/14
  fixed 1M config (radius 73984, cluster_num 1000, K 24, 10 % cache, error_bound 0.1, gt 8379,
  window 2).
- **Threads:** `OMP_NUM_THREADS=4`, `taskset -c 2,3,4,5`, `OMP_PROC_BIND=true OMP_PLACES=cores`.
- **Output:** computing logic is byte-for-byte unchanged; only the **output sink** is replaced by a
  new, output-only **per-thread streaming sink** (`GATE15_PER_THREAD_STREAM`). Reason: the existing
  buffered sink needs `398,737,742 × 16 B ≈ 6.38 GB` RSS, which **exceeds the 2 GiB cap**. The new
  sink writes thread `t`'s pairs to `GATE3_PAIR_OUT.t<t>` through a 4 MiB buffer (16 MiB total for 4
  threads). Patch: `inputs/DiskJoin_GATE15_PER_THREAD_STREAM.patch` (sha `adde6295…`), applied on top
  of the frozen step14 source (`ef0705f7…`) → `a9396e2c…`. It touches only the emit/handle path, not
  candidate generation, ordering, cache, pruning, threshold, distance or counters.
- **Comparison:** exact **multiset**, not counts/XOR/sum. Each side is sorted (`LC_ALL=C`, external,
  `-S 1G --parallel=3`, streamed through a FIFO) and the full sorted byte stream is SHA256-hashed; N,
  U and duplicates are counted in the same pass. Sorts run **sequentially** and no full sorted file is
  retained, so peak disk stays within budget.

### 2.2 Sink validation (100K, fast)

Before the 1M run, the new sink was validated on 100K at 1 and 4 threads
(`validate_100k/`, `tools/validate_100k_sink.sh`): concatenated per-thread output for **both** thread
counts is byte-identical to the step2 reference sorted stream (`e57f9e5d…`), exact count
`154,113,486`, rc=0. This proves the sink is output-only (a logic change would change the multiset).

### 2.3 1M result

Run `correctness_1m/t4` (`tools/run_1m_4thread.sh`):

| item | value |
|---|---|
| process rc | **0** |
| per-thread sink | `[gate15] pairs=398737742 threads=4 per_thread_stream=1` |
| recall / sampled_count | `0.855114` / `7165` (gt 8379) |
| exact `dist_comp_exact` | **14,090,491,387** |
| float `dist_comp` (saturating) | 14,021,578,752 |
| read_calls / effective_bytes | 4670 / 2,466,615,808 |
| wall / CPU% | 88.3 s / 365 % |
| peak RSS | 104,664 kB ≈ **102 MB** |

Aggregation (`tools/compare_multiset_1m.sh`), both sides:

| | sha256 (sorted full stream) | N | U | duplicates | sort/tee/awk/sha rc |
|---|---|---:|---:|---:|---|
| 4-thread GATE15 sink | `863affa82351e61f991d934fb09cb5b80472d4f89c41a5fc258ccc76db29123a` | 398,737,742 | 398,737,742 | 0 | 0/0/0/0 |
| step7 1-thread ref | `863affa82351e61f991d934fb09cb5b80472d4f89c41a5fc258ccc76db29123a` | 398,737,742 | 398,737,742 | 0 | 0/0/0/0 |

- **Result: MULTISETS IDENTICAL** (exact full sorted-stream SHA256 match; `correctness_1m/COMPARISON_RESULT.txt`).
- **Last-group settlement / exit codes:** per-thread raw line counts sum to exactly 398,737,742 = N =
  step7 ref line count; every raw file ends in `\n`; `U == N` means the final sorted group was a
  counted singleton (nothing dropped); all sort/tee/awk/sha256 exit codes are 0.
- **Transparency note:** the aggregation was run twice. The first pass already produced the identical
  SHA256/N/U (both sides `863affa8…`, N=U=398,737,742) but its wrapper script failed to *record* the
  exit codes (a `PIPESTATUS` capture bug), so the sort exit-code evidence would have been missing. The
  script was fixed and re-run from scratch; the records in `agg_t4.*` / `agg_ref.*` are from the
  corrected pass. Both passes agreed on the multiset. This re-run is why sort wall time was spent
  twice; total round wall stayed within the 30 min cap (no single run exceeded it).

---

## 3. Frozen baseline

`CPU_BASELINE_MANIFEST.json` (validated JSON) fixes: source + patch chain, compiler/options, binary
hashes, data manifest, graph, tasks, config, CPU topology + binding, GT/eval protocol, and three named
configurations:

| id | impl | threads | build? | binary |
|---|---|---|---|---|
| **A** | original loops | 1 (`-c 2`) | **includes build** | step7 `7524590e…` |
| **B** | optimized C (`GATE13_C_PATH`) | 1 (`-c 2`) | **includes build** | step13 `a707e927…` |
| **C** | optimized C (`GATE13_C_PATH`) | 4 (`-c 2,3,4,5`) | **reuses fixed graph** (`GATE14_SKIP_BUILD`) | step14 `632884c7…` (perf), step15 `d712ec53…` (correctness) |

Which comparisons include the build vs reuse a fixed graph is marked per comparison in the manifest:
step13 A-vs-B includes the build in both; the step15 4-thread correctness run **reuses** the fixed
step13 graph (its reference, step7, included its own build); the 100K thread comparisons **reuse** the
fixed step2 graph.

**Evidence scopes kept separate:** sampled Recall (IDs divisible by 100000 / `gt`; 1M 0.855114,
100K 0.666667) vs full-output consistency (complete pair multiset equality). **Normal-run no-error**
(step14/15, rc=0, no error strings) is recorded separately from **sanitizer** verification
(step13's separate ASan+UBSan 100K run, rc=0, `CMP=IDENTICAL`); the 1M step15 run is not a sanitizer
run.

Wording tightened (manifest `wording_constraints`): no "unique bottleneck", no "load balance proven";
the 4-core result is an Amdahl-limited CPU scaling measurement, not a GPU claim; sampled recall is not
full-join recall.

---

## 4. Resources

| cap | limit | used |
|---|---|---|
| wall | 30 min | 1M run 88.3 s; sorts ~3.6 min each (sequential) — within |
| CPU | ≤4 | `taskset` 4 cores; `sort --parallel=3`; ≤4 throughout |
| process-tree RSS | 2 GiB | 1M run 102 MB; `sort -S 1G` ≈1 GB — within |
| new disk | 16 GiB | 1M pairs 5.50 GB + build/logs ≈ **5.5 GB** — within |

Peak disk was computed before running: raw pairs 5.5 GB + sort spill (streamed, no full sorted file)
≈5.5 GB ⇒ ≈11 GB peak, under 16 GiB. Only this round's marked sort temporaries were removed
(`tmp/`); all old assets and the new raw per-thread output are retained.

---

## 5. Integrity

- Git HEAD unchanged: `ae56a37f9ded89e4d7d7e6fac1077e9e5d7f3c5e`; no commit/push/reset/clean; no
  download; no GPU. `gate5ar/scripts/run_linux.sh` (pre-existing modification) untouched.
- Old assets (steps 2,7–14 graphs, pairs, logs, reports) unmodified; erratum, manifest and report are
  new files.
- Compute logic unchanged; the only source change this round is the output-only sink, verified by the
  100K multiset check and the 1M exact match.

### Evidence package (`runs/step15_cpu_scaling/`)

```
CPU_BASELINE_MANIFEST.json
STEP15_REPORT.md
erratum/STEP15_DIST_COMP_ERRATUM.md
inputs/DiskJoin.h.before_step15, DiskJoin_GATE15_PER_THREAD_STREAM.patch
inputs/source_before_step15.sha256, source_after_step15.sha256, step15_binary.sha256
build/{main, ...}
validate_100k/t{1,4}/{pairs.txt.t*, pairs.sorted, stdout.log, stderr.log, rc.txt}
                sorted_hashes.txt
correctness_1m/t4/{config, pairs.txt.t0..t3, stdout.log, stderr.log, rc.txt}
correctness_1m/{agg_t4.*, agg_ref.*, COMPARISON_RESULT.txt}
logs/{driver.log, cmake_configure.log, build.log}
tools/{run_1m_4thread.sh, validate_100k_sink.sh, aggregate_multiset.sh, compare_multiset_1m.sh}
tmp/   (sort spill; emptied after aggregation)
```
