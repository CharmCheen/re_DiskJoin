# Gate 5B — Step 13: step12 "version C" integrated into the full BigANN1M join

Date: 2026-11-03 · Host: `amax` · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`
Round dir: `workspace/gate5b/runs/step13_c_integration/` (all new artifacts; step7–12 evidence untouched)
Reference: step12 replay `runs/step12_compute_replay/` (the compute-loop baseline this integrates).

**Question.** Does the step12 compute-loop "version C" (blocked, register-reuse, inline kernel) survive
integration into the real DiskJoin join, stay **byte-identical** end-to-end, and produce an **end-to-end**
wall-time gain? No GPU; this is a **CPU-baseline optimization validation**, not a novelty claim.

**Bottom line.** Correctness: **YES, fully identical** — the 1M join with the C path emits a pairs file
that is **byte-for-byte identical** (same sha256) to the verified normal output, with identical
`dist_comp`, `sampled_count`, pairs, graph and task-order hashes. Performance: see §4
(end-to-end result and whether the step12 compute-loop gain transfers).

---

## 1. Interpretation scope (keep step12 separated; report both reduction % and speed-up)

The step11 erratum and step12 report are **preserved unchanged**. This round keeps the attribution
boundaries explicit:

| change | what it bundles | attribution status |
|---|---|---|
| **A → B** (step12) | indirect call → **direct call + constant propagation** of `d = 128` | measured in step12; the compile emits a resolved `call …constprop.0` (no function-pointer indirection, dimension dispatch removed) |
| **B → C** (step12) | **operand reuse + memory layout + full inlining** of the AVX-512 kernel | **bundled, not separated** — step12 did not decompose these three sub-effects |

This round integrates the **A → C** change as one package. When reporting a gain, both quantities are
given and never mixed:

- **time reduction %** = `(T_A − T_C) / T_A × 100`
- **speed-up ratio** = `T_A / T_C`

They are different numbers (e.g. `−18.7 %` time reduction ⇔ `1.23×` speed-up); the report labels each.

## 2. Minimal integration

- **Baseline = the verified normal version.** The only source change is an **env-gated C path** in the
  fixed-128 point–point loops; the default (gate unset) is the original loop, unchanged.
- **Gated on `GATE13_C_PATH` AND runtime `d == 128`.** Any other dimension keeps the original
  `utils::dist_l2` path; the gate is read once per join.
- **Invariants preserved:** candidate set, upper-triangle filter (`id2 >= id1`), strict threshold
  (`dist < epsilon*epsilon`), task order, pair emit order, and float accumulation are unchanged.
- **No new fast-math**: the kernel reuses the exact `_mm512_sub_ps` / `_mm512_fmadd_ps` order and the
  same `HsumFloat128` tail as `L2SqrFloatAVX512` (bit-identical by construction; §3.1 proves it).
- **Audited paths** (same-bucket, cross-bucket, tail, alignment, empty bucket, boundary access):
  - same-bucket: gather up to `GATE13_BLK = 16` valid `vec2` (skipping `id2 >= id1`) per block, compute,
    then apply the original judgment in encounter order → emit order preserved;
  - cross-bucket: gather every `vec2 = data + k*length + l*d`; the original (unused) point-to-centroid
    call is **kept** so only the point–point compute changes;
  - **tail block**: a partial block (`gcnt < 16`) is computed and judged the same way;
  - **alignment**: `_mm512_loadu_ps` for both operands (same as the kernel), so unaligned bases are safe;
  - **empty bucket**: `n == 0` blocks are skipped (`if (gcnt)`), and the pre-existing
    `bucket_sizes[target_cluster] == 0` guard is untouched;
  - **boundary access**: vectors are 128 floats (512 B); the helper reads exactly `v2 + 0 .. v2 + 127`.
- **Patch:** `inputs/DiskJoin_GATE13_C_PATH.patch` (pre-image `inputs/DiskJoin.h.before`), new header
  `instrumented/DiskJoin/lib/gate13_l2.h`.
- **Compiled-artifact check** (`logs/omp_fn1_disasm.txt`, `nm`/`objdump` of `build/main`,
  `DiskJoin::search … [clone ._omp_fn.1]`): the C path is **inlined** — the object has **no**
  `gate13_l2sq_block128` symbol, and the compute-loop function contains **36 `vfmadd231ps`** and **124
  `zmm`** instruction lines; the original path's memory-indirect call sites
  (`call *…(%rip) # <dist_l2>`) are still present for the non-128 / gate-off case. So this build contains
  **both** the baseline loop and the inlined C loop, selected at runtime by the gate.

## 3. Correctness

### 3.1 Unit test — distance bit-level identity + strict boundary (`tools/test_gate13_l2.cpp`)

Result: **PASS, 8067 checks, 0 fails** (`logs/unit_gate13_l2.txt`):

- 400 trials × blocks of size 1..16 with multi-block tails, **deliberately unaligned** v1/v2 offsets:
  every blocked distance is **bit-identical** (`memcmp` on the float bits) to `utils::L2Sqr`.
- strict threshold boundary: a vector pair with squared distance exactly **`73984.0f`** (= `272²`) →
  helper returns exactly `73984` and `dist < 73984` is **FALSE** (both helper and reference);
  a just-below value (`271.9999²`) **passes**.
- empty block (`n = 0`) is a no-op (no dereference; output untouched).

### 3.2 Existing deterministic regression

`python3 -B -m unittest tests.test_correctness` → **Ran 10 tests … OK** (`logs/test_correctness.txt`).

### 3.3 ASan + UBSan 100K join with the C path (`tools/run_asan_100k.sh`)

C path enabled, streaming pairs, `-O1 -g -fsanitize=address,undefined`. Result:
**rc = 0, 0 sanitizer hits**, and **pairs byte-identical** to the frozen step2 100K normal output
(sha256 `8d2ed373…`), with identical `dist_comp = 154,113,552`, `sampled_count = 2`, pairs = `3,855,811`,
cache/IO stats and `recall = 0.666667`.

### 3.4 Full 1M join, C path, streaming pairs → byte-for-byte vs normal

`tools/run_correctness.sh` (correction run, `GATE13_C_PATH=1`, `GATE3_PAIR_STREAM=1`, `OMP_NUM_THREADS=1`):

| quantity | C path (step13) | normal reference (step7) | match |
|---|---|---:|---|
| rc | 0 | 0 | ✅ |
| `dist_comp` | 10,701,217,792 | 10,701,217,792 | ✅ |
| `sampled_count` | 7165 | 7165 | ✅ |
| `pairs` | 398,737,742 | 398,737,742 | ✅ |
| pairs bytes | 5,497,538,938 | 5,497,538,938 | ✅ |
| `recall` | 0.855114 | 0.855114 | ✅ |
| pairs sha256 | `cfb4b9c0be815e52e938464865c51b94cefb29d1affe470dcad60e6d9685e69a` | same | ✅ |
| `cmp` byte-for-byte | — | — | **IDENTICAL** |
| graph hashes | `8f688ef1…` / `86827ea7…` / `eb0be0ed…` | same | ✅ |
| task order | `d699f722…` | same | ✅ |

⇒ The full 1M output is **byte-identical**; correctness gate **passed**, so performance measurement is
allowed. (Per the task, the compute time recorded inside this 5.5 GB-pair run is **not** used to infer a
compute speed-up.)

## 4. Performance — end-to-end 1M, A (baseline) vs C, 3 runs each

Fixed: 10 % cache (`mem_budget 0.0476837158203125`), `radius 73984`, `cluster_num 1000`, `K 24`,
`error_bound 0.1`, `gt 8379`, `GATE4B0_WINDOW=2`, `OMP_NUM_THREADS=1`, `taskset -c 2`, pair/trace output
OFF (`GATE3_COUNT_ONLY`). Same binary, same counters, same `GATE5B_PROFILE` phase timing for both.
Run order alternates **A / C / C / A / A / C**. This round's baseline is re-measured (no old runtimes).

Per-run data (all 6 runs rc=0):

| run | var | build_s | search_s | compute_s | preload_s | proc_s | elapsed_s | RSS_MiB | dist_comp | pairs | reads |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r01_A | A | 16.564 | 286.226 | 277.485 | 8.408 | 302.790 | 302.800 | 97.5 | 10,701,217,792 | 398,737,742 | 4670 |
| r02_C | C | 15.837 | 247.577 | 238.793 | 8.453 | 263.414 | 263.420 | 97.5 | 10,701,217,792 | 398,737,742 | 4670 |
| r03_C | C | 15.801 | 247.445 | 238.720 | 8.393 | 263.246 | 263.250 | 97.5 | 10,701,217,792 | 398,737,742 | 4670 |
| r04_A | A | 15.801 | 286.233 | 277.363 | 8.537 | 302.034 | 302.040 | 97.5 | 10,701,217,792 | 398,737,742 | 4670 |
| r05_A | A | 15.752 | 285.660 | 276.780 | 8.550 | 301.412 | 301.410 | 97.5 | 10,701,217,792 | 398,737,742 | 4670 |
| r06_C | C | 15.920 | 249.282 | 240.494 | 8.459 | 265.201 | 265.200 | 97.5 | 10,701,217,792 | 398,737,742 | 4670 |

Means (A = 3 baseline runs, C = 3 C-path runs). **Both** time reduction % and speed-up are shown:

| phase | mean A (s) | mean C (s) | time reduction | speed-up |
|---|---:|---:|---:|---:|
| build (k-means) | 16.039 | 15.853 | 1.16 % | 1.012× |
| **search** | **286.040** | **248.101** | **13.26 %** | **1.153×** |
| ├ **compute** | **277.210** | **239.336** | **13.66 %** | **1.158×** |
| └ preload | 8.498 | 8.435 | 0.74 % | 1.008× |
| **process (build+search)** | **302.079** | **263.954** | **12.62 %** | **1.144×** |
| RSS | 99,859 kB | 99,859 kB | 0 % | 1.000× |

All six runs produced identical `dist_comp = 10,701,217,792`, `sampled_count = 7165`, `gt = 8379`,
`pairs = 398,737,742`, `read_calls = 4670`, `effective_bytes = 2,466,615,808`. No sanitizer/error strings.

### 4.1 Reading of the result

- The only accelerated fraction is the **compute** phase; `build` and `preload` (and the cache behaviour)
  are unchanged within noise (1.16 % / 0.74 %), and all counters are identical — so the gain is **not**
  from reducing candidates, changing pruning, I/O or the cache.
- **Compute** is the phase the C path changes directly: 277.21 s → 239.34 s, i.e. **−13.66 % time**
  (**1.158× speed-up**). This is the end-to-end confirmation of the step12 replay, whose compute-loop
  A→C speed-up was **1.187×** (~+18.7 %). The real-run compute gain is somewhat smaller, consistent with
  the replay having a smaller, warmer working set.
- Because the process is dominated by compute (step11: compute ≈ 96.8 % of search), the whole process
  inherits most of it: **302.08 s → 263.95 s**, i.e. **−12.62 % process wall** (**1.144× speed-up**).
  This is an **Amdahl-consistent** outcome, not a surprise extrapolation: the compute share × the compute
  speed-up explains the process change (0.9683 × 13.66 % ≈ 13.2 % of search; measured 13.26 %).
- **Step12 replay result transfers.** Unlike a purely micro-benchmark win, the C path shows a real
  end-to-end gain on the full 1M join with byte-identical output. It is a genuine CPU-baseline
  optimization; it is **not** a research-novelty claim.

## 5. Conclusion

1. **Full 1M results are identical.** The C-path join's pairs output is byte-for-byte identical to the
   verified normal output (sha256 `cfb4b9c0…`), with identical `dist_comp`, `sampled_count`, `gt`, pairs,
   graph and task-order hashes. The 100K ASan+UBSan run is also byte-identical and sanitizer-clean.
2. **End-to-end gain is real.** Process wall **302.08 s → 263.95 s** = **−12.62 % time / 1.144× speed-up**;
   search **286.04 s → 248.10 s** = **−13.26 % / 1.153×**; compute **277.21 s → 239.34 s** = **−13.66 % /
   1.158×**.
3. **The gain is a CPU baseline optimization, not the replay-only artifact.** The step12 compute-loop
   gain (≈1.19×) transfers to the real join (compute 1.158×, process 1.144×), reproduced across the
   alternating A/C order with 3 runs each.
4. **Attribution is still partial.** This validated the **A→C** package (indirect-call removal +
   constant propagation **and** operand reuse + layout + inlining). The **B→C** sub-effects
   (reuse vs layout vs inlining) remain **unseparated** (step12 noted this too).
5. **Positioning.** This is a **CPU-baseline optimization validation** for a future batched/heterogeneous
   executor. It carries no novelty claim, makes no GPU claim, and does not claim the gain generalizes
   beyond the fixed configuration (`d = 128`, 10 % cache, single thread, this host, BigANN1M).

## 6. Resources (caps: 60 min wall / ≤4 CPU / join 1 thread / RSS ≤4 GiB / new disk ≤8 GiB)

- Round wall: 16:39 → 17:22 ≈ **43 min**; under 60 min.
- CPU: join pinned `taskset -c 2`, `OMP_NUM_THREADS=1`; builds `--parallel 4`/`--parallel 2`; ≤ 4 CPU.
- Join RSS: peak ≈ 100 MB (1M) — well under 4 GiB.
- New disk: `step13_c_integration/` = **5.72 GiB** (correctness pairs 5.1 GB + graph 0.5 GB + ASan build
  + ASan 100K run) — under 8 GiB.
- No download, no GPU, no deletion; no commit/push/reset/clean.

## 7. Deliverables

- `inputs/DiskJoin.h.before`, `inputs/DiskJoin_GATE13_C_PATH.patch`, `inputs/source_{before,after}.sha256`.
- `instrumented/DiskJoin/lib/gate13_l2.h`, `lib/DiskJoin.h` (patched).
- `tools/{test_gate13_l2.cpp, run_correctness.sh, run_asan_100k.sh, run_perf.sh, summarize_perf.py}`.
- `build/` (Release), `asan_build/` (ASan+UBSan).
- `correctness/` (1M C-path run, pairs, counters), `asan_100k/`, `perf/r01_A … r06_C`, `graph/`.
- `logs/` (unit test, deterministic regression, ASan run, perf summary, compiled-artifact disasm).
