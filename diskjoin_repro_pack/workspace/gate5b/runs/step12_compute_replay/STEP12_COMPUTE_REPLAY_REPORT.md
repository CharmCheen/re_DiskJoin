# Gate 5B — Step 12: compute-loop CPU headroom — source audit + bounded real-task replay

Date: 2026-11-03 · Host: `amax` · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`
Round dir: `workspace/gate5b/runs/step12_compute_replay/` (all new artifacts; step7–11 evidence untouched)
Companion: `runs/step11_hotspot_profile/STEP11_ERRATUM.md` (scope correction to the step11 report)

**Question.** How much CPU headroom is left *inside* the step11 "compute" phase (the 96.83 % hotspot),
separating (i) the function-pointer indirection, (ii) batching / operand reuse, and (iii) the
not-yet-separated pruning/branch + result handling — to set a baseline for a future batched or
heterogeneous execution path. **No GPU this round.** Audit by **compiled artifacts**, not source alone,
and bound any speed claim to a small set of real tasks.

**Bottom line (bounded).** On three complete real tasks (48,404,888 candidates over the real 1M vectors):

| variant | what it changes | mean compute-loop wall | vs A |
|---|---|---:|---:|
| **A** | original loop, indirect call through the global `dist_l2` | 1.013273 s | — |
| **B** | same loop, direct call to the same AVX-512 kernel, fixed `d=128` | 0.916421 s | **B/A ≈ +10.6 %** |
| **C** | blocked (16), `vec1` held in registers, kernel inlined, then the **original** judgment | 0.853417 s | **C/A ≈ +18.7 %** |

All three are **bit-identical** on candidates, the passing set, emitted pairs, every distance's bits and
the strict `< 73984` boundary (142 exact-equality distances). **These numbers are compute-loop-local and
apply only to these tasks** — see §5.

---

## 0. Method & scope

- This is **not** a patched DiskJoin build. It is a standalone C++ harness (`tools/replay.cpp`) that
  replicates the real computation exactly and drives it over **real** vectors, **real** candidate order
  and the **real** working-buffer layout (2 MB / 13 MB / 26 MB, same slot stride as the join).
- Three versions A/B/C run on the **same** input within one process, round-robin, **after a warm-up
  pass**, then ≥5 timed passes. Single thread, pinned `taskset -c 2`, `OMP_NUM_THREADS=1`.
- The compiler is prevented from eliminating work by a candidate counter (`dist_comp` analogue) and the
  threshold branch; verification mode additionally accumulates an order-independent XOR of every
  distance's float bits, a hash of the emitted pair set, the candidate count, a pass counter and an
  exact-`73984.0f` boundary probe. The timed loop keeps the counter + branch (matching the real loop)
  and drops the hashing.
- **No candidate is reduced, no pruning is changed and no precision is relaxed** to obtain speed:
  A/B/C execute the identical candidate set and the identical `<`-test, and are proven equal.

---

## 1. Source-location audit

All line numbers are the **instrumented copy** `instrumented/DiskJoin/` that carries step11's
`GATE5B_PROFILE` patch; the compute loop is `lib/DiskJoin.h:352–385`.

### 1.1 The three distance sites in the join

| site | line | call | counted? | loop shape |
|---|---|---|---|---|
| same-bucket point–point | `lib/DiskJoin.h:360` | `dist_l2(vec1, vec2, &d)` | yes (`dist_comp++` `:361`) | inner `l` over the target bucket, `vec2 = data + l*d` |
| point–**centroid** | `lib/DiskJoin.h:371` | `dist_l2(vec1, centroids + neighbor_cluster*d, &d)` | **no** | once per (point, neighbour bucket) |
| cross-bucket point–point | `lib/DiskJoin.h:375` | `dist_l2(vec1, vec2, &d)` | yes (`dist_comp++` `:376`) | inner `l` over neighbour bucket, `vec2 = data + k*length + l*d` |

`dist_l2` is an **external-linkage mutable global function pointer**:
`auto dist_l2 = utils::L2Sqr;` (`lib/ClusterIO.h:20`). It is therefore a *mutable* global
(symbol `D dist_l2`), which is exactly why the compiler cannot resolve the callee.

Kernel path: `dist_l2` → `utils::L2Sqr` (`utils/dist_func.h:612`) → `L2SqrSIMD` (`:475`) →
`L2SqrFloatAVX512` (`:60`). The AVX-512 kernel runs a `while (dim >= 16)` loop; at **d=128 it iterates 8
times** (8 `_mm512_loadu_ps(pVec1)` / `_mm512_loadu_ps(pVec2)` / `_mm512_sub_ps` / `_mm512_fmadd_ps`
groups) and then skips the 8/4/tail paths.

*Minor, recorded for completeness:* the point–centroid distance at `:371` is computed and **never used**
by the following loop (`:372–382`); it is dead arithmetic at ≈ `Σ_i bucket_size_i·(tasks_i−1)` ≈ 1.1e7
calls ≈ 0.1 % of `dist_comp` (step11 already noted it is uncounted). It is not part of the A/B/C compare.

### 1.2 Which distance computations can be independently batch-executed? — **all of them**

For **both** counted loops, `vec1` is **loop-invariant across the entire inner segment**:
- same-bucket: `vec1 = data + j*d` is fixed while `l` runs over the whole target bucket;
- cross-bucket: `vec1` is fixed while `l` runs over the neighbour bucket.

Each candidate distance is `f(vec1, vec2_l)` and **depends on no other distance**. There is no
sequential dependence whatsoever between candidates, so the segment is **trivially batchable** — a
block of `vec2_l` can be computed in any order, in vector lanes, or offloaded, and the results
re-associated afterwards.

### 1.3 Does pruning depend on prior results? — **no**

The only "pruning" in the loop is:
- the upper-triangle filter `if (id2 >= id1) continue;` (`:358`) — a **static ID comparison**, not a
  distance;
- the threshold branch `if (dist < epsilon*epsilon)` (`:362`, `:377`) — a **per-pair** test whose body
  only increments `count` and (in pair-output mode) emits.

There is **no branch-and-bound**: no candidate is skipped because an earlier distance was large/small.
So batching does not change which candidates are evaluated or which pairs are emitted — batching is
**semantically safe** (confirmed bit-identically in §4).

### 1.4 Vector reuse, memory access and result handling

- **Operand reuse:** the kernel reloads **both** operands every call. `vec1`'s 128 floats (exactly
  **8 `zmm`**) are identical for the whole inner segment but are **re-read for every candidate** — pure
  redundant load traffic (8 vector loads per candidate that do not have to happen). `vec2` streams once
  per candidate. This is the headroom C exploits.
- **Memory access:** `vec2` is contiguous with stride `d` within a bucket; across neighbour buckets it
  jumps by `length = max_points*d = 325248` bytes. `vec1` is reused; the working buffer is the join's
  own `data`. No gather/scatter is required.
- **Result handling:** per candidate, `dist_comp++` (an OMP reduction variable) and one compare; on the
  rare pass (`dist < thr`) two `% 100000` checks and a count/emit. In the replay's robust runs
  `count = 0` and `npass = 3,004,159` of 48.4 M (≈ 6.2 %) — the branch is mostly not-taken. This cost is
  **identical in A, B and C** and is therefore **not separated** by this experiment.

### 1.5 Can the function-pointer call be inlined at fixed d=128? — **no (compiled-artifact evidence)**

Determined from **`objdump` of the actual binaries**, not from source:

- **Real program** `runs/step11_hotspot_profile/build/main`, `DiskJoin::search … [clone ._omp_fn.1]`,
  site `0x12895`:
  ```
  12895: ff 15 7d 67 02 00   call *0x2677d(%rip)   # 39018 <dist_l2>
  ```
  a **memory-indirect call** through the global pointer — definitely **not inlined**.
- **Replay, variant A** (`build/replay`, `run_A` @ `0x4c00`): two sites, both
  `call *0x…(%rip) # c010 <dist_l2>` → faithful reproduction of the real indirection.
- **Replay, variant B** (`run_B` @ `0x5070`): `call 4f90 <utils::L2SqrFloatAVX512…[clone .constprop.0]>`
  — a **direct** call, but the kernel is still **out-of-line** (GCC did *not* inline the unrolled
  AVX-512 body even for the direct, `d=128`-constant case); the win is that the call target is fixed and
  the dimension dispatch (`while(dim>=16)` + `dim` load) is const-propagated away (`[clone .constprop.0]`).
- **Replay, variant C** (`run_C` @ `0x5540`): **0 `call` instructions** — the kernel is fully inlined and
  `vec1`'s 8 `zmm` are held across the block; the function then contains the `vfmadd` groups directly.

**Answer:** with the current call graph (`dist_l2` = *mutable global pointer of external linkage*) the
call is a true indirect call and **cannot be inlined**. Even removing the pointer (direct call, fixed
`d=128`) does **not** get the kernel inlined in this TU; only writing the kernel inline (C) does.
Raw evidence: `logs/indirect_call_evidence.txt`.

---

## 2. Replay input list (fixed IDs + deterministic selection rule)

Selection is **deterministic, no randomness** (`tools/select_tasks.py`): from the **real** 1M task graph
(`runs/step11_hotspot_profile/runs/profile_10pct/tasks.txt`) and metadata
(`graph/data.metadata`), each slot's **exact** candidate count is computed as

```
cand(slot) = C(n_target, 2) + n_target · Σ_{neighbour k≥1} bucket_size[k]
```

and slots are picked at the **10th / 50th / 95th percentile** of `cand` → small / medium / large.
Written to `inputs/replay_tasks.txt`:

| label | slot | target | candidates | deg | n_target | cross vectors |
|---|---:|---:|---:|---:|---:|---:|
| small | 909 | 912 | 1,962,590 | 2 | 1060 | 1322 |
| medium | 520 | 669 | 11,578,248 | 10 | 1089 | 10088 |
| large | 90 | 99 | 34,864,050 | 20 | 1300 | 26169 |
| **total** | | | **48,404,888** | | | |

Observed candidate-count distribution over all 1000 slots: min 10,585, p50 11,578,248, p95 35,591,661,
max 90,659,093 — so the three tasks span ≈ p10 … p95 of the whole workload.

The harness loads, for each selected task, the **real** vectors of its target and every neighbour bucket
into a buffer with the **real slot stride** (`length·4 = 1,300,992` bytes) and the **real candidate
order** (assignment arrays as stored). No random or synthetic vectors are used. Total real bytes loaded
= **21,006,336**. Buffers: 2,601,984 / 13,009,920 / 26,019,840 bytes.

---

## 3. Versions A / B / C (identical math, different loop/kernel form)

- **A — original:** the exact loop structure of `DiskJoin.h:352–385` (per-`j` same-bucket loop with
  `id2 >= id1` skip, then cross-bucket), distance through the **external-linkage mutable global**
  `float (*dist_l2)(…) = utils::L2Sqr;` → memory-indirect call, out-of-line kernel.
- **B — fixed 128-dim direct call:** the **same** loop; `utils::L2Sqr(v1, v2, &D)` called directly with
  `D = 128` compile-time constant → direct call, `constprop` kernel (dispatch removed). Loop/pruning/
  result handling unchanged.
- **C — blocked batch compute, then original judgment:** for a fixed `vec1`, gather up to `BLK = 16`
  candidate `vec2` pointers, compute their distances with **explicit AVX-512 intrinsics that replicate
  `L2SqrFloatAVX512`'s operation order exactly** (8 × {`loadu`,`subps`,`fmadd`} over 16 lanes, then
  `HsumFloat128`), holding `vec1`'s **8 `zmm` across the whole block**; then apply the **original**
  `id2 >= id1` skip (applied during fill) and the **original** `dist < epsilon*epsilon` judgment per
  result. Added buffers: **16 × (const float*)** + **16 × size_t** + **16 × float = 320 bytes** on the
  stack, plus 8 held `zmm`. No precision change: `_mm512_fmadd_ps` is used exactly as the kernel does.

### 3.1 Correctness (proof of equality)

One verification pass over all three, hashing every distance's bits (order-independent XOR), the
candidate count, the pass count, the emitted-pair set hash and the exact boundary count:

```
[verify] A ncand=48404888 npass=3004159 count=0 eqbound=142 dxor=0000000001a03da0 pairxor=5850e1aeb9b8e1d8 dsum=7868772100716
[verify] B ncand=48404888 npass=3004159 count=0 eqbound=142 dxor=0000000001a03da0 pairxor=5850e1aeb9b8e1d8 dsum=7868772100716
[verify] C ncand=48404888 npass=3004159 count=0 eqbound=142 dxor=0000000001a03da0 pairxor=5850e1aeb9b8e1d8 dsum=7868772100716
[verify] ALL THREE VERSIONS IDENTICAL (candidates, pass set, pair set, distance bits, boundary)
```

**Strict `< 73984` boundary:** `epsilon*epsilon = 73984.0f` exactly (`epsilon = sqrt(73984) = 272`
exactly). The test is `dist < 73984.0f`, **strict**. The replay found **`eqbound = 142`** candidate
distances whose float value is **exactly `73984.0f`**; all 142 are **excluded** by the strict `<`, and
the excluded set is **identical in A, B and C**. (If the code had used `<=`, 142 more pairs would pass —
the replay pins this behaviour.)

`count = 0` is expected here (the sampled-ID convention needs ids divisible by 100000 among the passing
pairs of *these* buckets and the `gt` normalisation is not applied in the harness); `npass = 3,004,159`
is the actual recall numerator over these tasks. The important property is the **equality** across A/B/C.

### 3.2 Per-pass times (single thread, `taskset -c 2`, warm-up pass then 7 timed passes)

| pass | A wall_s | B wall_s | C wall_s |
|---:|---:|---:|---:|
| 0 | 1.017110 | 0.922781 | 0.857121 |
| 1 | 1.015911 | 0.920011 | 0.851712 |
| 2 | 1.010382 | 0.910450 | 0.856070 |
| 3 | 1.010353 | 0.914949 | 0.850736 |
| 4 | 1.021936 | 0.909926 | 0.848308 |
| 5 | 1.007749 | 0.920427 | 0.857992 |
| 6 | 1.009467 | 0.916402 | 0.851982 |
| **mean** | **1.013273** | **0.916421** | **0.853417** |
| min | 1.007749 | 0.909926 | 0.848308 |
| median | 1.010382 | 0.916402 | 0.851982 |
| max | 1.021936 | 0.922781 | 0.857992 |

Each timed pass executes the **full 48,404,888 candidates** in every version (printed per pass).

Derived (mean-based): **B/A ≈ 1.106** (+10.6 %), **C/B ≈ 1.074** (+7.4 %), **C/A ≈ 1.187** (+18.7 %).
Per-candidate: A ≈ 20.93 ns, B ≈ 18.93 ns, C ≈ 17.63 ns.

---

## 4. Judgment — what is separated, and what is not

1. **Indirect-call elimination (B − A ≈ +10.6 %) — separated.** Removing the mutable-global
   function-pointer indirection and letting the compiler fix the callee + const-propagate `d=128` buys
   ≈ 10.6 % on the compute loop. Compiled evidence (§1.5): A = `call *…(%rip) # dist_l2`,
   B = `call …L2SqrFloatAVX512…constprop.0`. **This is a call-target/constant-propagation win, not an
   inlining win** — B's kernel is still out-of-line.
2. **Batching / operand reuse (C − B ≈ +7.4 %) — separated as a combined effect, not decomposed.**
   C avoids re-loading `vec1`'s 8 `zmm` for every candidate (register blocking) and lays candidates out in
   blocks. C also happens to be the only variant with the kernel **fully inlined** (`run_C`: 0 calls).
   So the +7.4 % bundles **operand reuse + block layout + inlining**; this experiment does **not**
   separate those three sub-effects from one another.
3. **Pruning/branch + result handling — NOT separated.** The upper-triangle `id2 >= id1` filter, the
   `dist < epsilon*epsilon` branch, `dist_comp++` and the (mostly not-taken, ≈6.2 %) pass handling are
   **identical in A, B and C**, so their cost is inside all three times and is not isolated. Step11
   already notes this; step12 does not remove it either.

**Combined compute-loop headroom measured here (C vs A): ≈ +18.7 %**, entirely non-GPU, using only
fixed-`d` direct calls and register blocking — no algorithm, candidate, pruning or precision change.

---

## 5. What the replay does and does not support

**Supports (for these three tasks):** the compute-loop-local speedups above; the exact equality of
candidate set, pruning outcome, emitted pairs, distance bits and the strict-`<` boundary; the
compiled-artifact call/inlining facts (which are general to the build, not task-specific).

**Does NOT support:**
- **Any whole-run speed-up claim.** The 48.4 M candidates are three tasks, not the 10.70e9 of a full run,
  and this harness has no I/O, no cache management and a much smaller working set (21 MB of vectors) than
  the join's streaming buffer, so cache residency differs. The number is compute-loop-local.
  *(For orientation only, not a prediction: applying the step11 Amdahl arithmetic literally,
  0.9683 × 18.7 % ≈ 18.1 % end-to-end — but that mixes a local, warm, reduced-working-set benchmark with
  a cold, streaming full run and must not be read as a forecast.)*
- **A clean split of the +7.4 %** into "inlining" vs "operand reuse" (§4.2).
- **The pruning/branch/result-handling share** (§4.3).
- **Anything about a batched/GPU/heterogeneous executor's real throughput** — this only bounds the CPU
  loop structure, which was the round's question.

The result is **not negative** (both B and C help, repeatably and bit-identically), but it is **bounded**.

---

## 6. Resources for this round (caps: 30 min wall / ≤4 CPU / replay 1 thread / RSS ≤4 GiB / new disk ≤1 GiB)

| measure | value | status |
|---|---|---|
| round wall | 16:25:36 (dir birth) → ~16:35 ≈ **9 min** | < 30 min |
| CPU | replay pinned `taskset -c 2`, `OMP_NUM_THREADS=1`; one compile | ≤ 4 CPU |
| replay peak RSS | **52,236 KB ≈ 51 MiB** (`/usr/bin/time -v`) | ≪ 4 GiB |
| new disk | `step12_compute_replay/` = **112 KB** | ≪ 1 GiB |
| replay runs | 1 main run (7 timed passes) + 1 RSS check (`runs/step12/…/rss_check.txt`) | — |
| downloads / GPU / git | none; no commit/push/reset/clean | — |

`perf` remained unavailable (step11), so this round deliberately does **not** rely on PMU sampling.

---

## 7. Deliverables

- `tools/replay.cpp` — A/B/C replay harness (the round's core code).
- `tools/select_tasks.py` — deterministic stratified task selection.
- `inputs/replay_tasks.txt` — the fixed replay input list (slots, candidates, rule).
- `build/replay` — compiled harness.
- `logs/replay_output.txt` — raw per-pass times + correctness hashes + summaries.
- `logs/indirect_call_evidence.txt` — compiled-artifact call/inlining evidence (real binary + replay).
- `logs/rss_check.txt` — peak-RSS evidence.
- `runs/step11_hotspot_profile/STEP11_ERRATUM.md` — scope correction to step11 (separate file).

Reproduce:
```
g++ -O3 -march=native -mavx2 -mfma -pthread -std=c++11 \
    -I instrumented/DiskJoin tools/replay.cpp -o build/replay
python3 -B tools/select_tasks.py
taskset -c 2 env OMP_NUM_THREADS=1 ./build/replay \
    runs/step11_hotspot_profile/graph/data.metadata \
    runs/step11_hotspot_profile/runs/profile_10pct/tasks.txt \
    inputs/replay_tasks.txt \
    runs/step11_hotspot_profile/graph/data.clusters 7
```
