# Step 15 Erratum — `dist_comp` is a **saturating `float`**, not a distance count

Date: 2026-11-03 · Round: `workspace/gate5b/runs/step15_cpu_scaling/`
Status: **correction only.** All prior reports and raw evidence are kept as written. No measured
timing, log, counter dump or output file has been modified. This document corrects statements that
used the `float dist_comp` value as a *distance-call count* or derived a *rate* from it.

---

## 1. Exact counter type, increment sites and OpenMP reduction

### 1.1 Old counter (original implementation, still present)

```c
float dist_comp = 0;                       // lib/DiskJoin.h, in DiskJoin::search()
...
#pragma omp parallel for schedule(dynamic) reduction(+:sum) reduction(+:count) reduction(+:dist_comp)
```

- **Type:** `float` (IEEE-754 binary32, 24-bit significand).
- **Increment sites (2 logical):**
  1. same-bucket upper-triangle point–point loop: `dist = dist_l2(vec1, vec2, &d); dist_comp++;`
  2. cross-bucket point–point loop: `dist1 = dist_l2(vec1, vec2, &d); dist_comp++;`
- **Not counted:** the point-to-centroid call `dist_l2(vec1, centroids + neighbor_cluster*d, &d)`,
  once per (point, neighbour bucket) ≈ `Σ_i bucket_size_i·(tasks_i−1)` ≈ 1.1e7 calls. Against the
  **exact** 1M count that is 1.1e7 / 1.409e10 ≈ **0.078 %** — still negligible, and it runs in the
  same `compute` region.
- **Reduction:** `reduction(+:dist_comp)` on the same `#pragma omp parallel for` (line 377 in the
  step15 source). OpenMP makes a *private `float` per thread per parallel region*, initialised to 0,
  and combines partials with `float` addition.

### 1.2 Exact counter (added in step 14, diagnostic only)

```c
size_t g14_dist_exact = 0;                 // 8 bytes on this LP64 host
#pragma omp parallel for ... reduction(+:g14_dist_exact)
```

- **Type:** `size_t`; `sizeof(size_t) = 8` on this host (verified). 64-bit is *required* — counts
  reach 1.4e10, far above 2^32.
- **Increment sites:** identical logical sites; incremented on the very same line as `dist_comp++`
  at every site (current source: lines 406/435 on the C path, 450/465 on the original path).
- **Reduction:** `reduction(+:g14_dist_exact)` — exact integer addition; no saturation, no rounding,
  thread-partition independent.
- Printed only when `GATE14_EXACT_COUNT` is set: `[gate14-exact] dist_comp_exact=<value>`.

### 1.3 Why they differ

A `float` represents every integer up to 2^24 = 16,777,216, but above that the increment `x+1` is
partly or fully absorbed by rounding. The `dist_comp` reduction keeps one private `float` per thread
per target-cluster region. When a single thread accumulates a large per-region total (> 2^24),
`dist_comp++` stalls and the region is under-counted.

- **1 thread** assigns every large cluster to one thread ⇒ the largest per-region partials far exceed
  2^24 ⇒ severe under-count (**−24 %** on 1M).
- **4 threads** split each cluster's points across threads ⇒ each private partial is smaller ⇒ only
  small rounding error (**−0.5 %** on 1M).
- At **100K** per-region totals stay below 2^24, so the per-region float is essentially exact; only
  the outer accumulation over ~1000 clusters rounds, and that accumulation is thread-invariant (hence
  the same value for 1/2/4 threads). The residual is **+66** on 154 M.

Also note: `[gate3-stat] dist_comp=…` prints `(size_t)dist_comp` — a truncation of the *saturated
float*. Casting does **not** recover the true count.

---

## 2. Old (float) vs new (exact) counts — recorded evidence

### 2.1 BigANN1M (config: radius 73984, K 24, 10 % cache, `gt 8379`)

Exact count is invariant: **14,090,491,387** in all of step14 (t1/t2/t4) and the step15 t4 run.

| run | OMP threads | old `dist_comp` (float) | new exact (`size_t`) | Δ (exact − float) | Δ % |
|---|---:|---:|---:|---:|---:|
| step14 r1/r6/r8 (`t1`) | 1 | 10,701,217,792 | 14,090,491,387 | +3,389,273,595 | **+24.05 %** |
| step14 r2/r4/r9 (`t2`) | 2 | 13,317,07x,xxx | 14,090,491,387 | ≈ +773,412,000 | ≈ +5.49 % |
| step14 r3/r5/r7 (`t4`) | 4 | 14,0xx,xxx,xxx | 14,090,491,387 | ≈ +69M…+74M | ≈ +0.49 % |
| step15 t4 (this round) | 4 | 14,021,578,752 | 14,090,491,387 | +68,912,635 | +0.489 % |

The float value also **varies run-to-run at fixed thread count** (e.g. t4: 14,021,633,024 /
14,021,642,240 / 14,016,656,384 / 14,021,578,752), because the reduction's rounding order changes.
The exact value does not.

### 2.2 BigANN100K (config: radius 73984, `gt 3`)

Exact count **154,113,486**, identical across 1/2/4 threads (step14) and step15's re-run.

| run | old `dist_comp` (float) | new exact (`size_t`) | Δ (exact − float) | Δ % |
|---|---:|---:|---:|---:|
| step14 t1 / t2 / t4 | 154,113,552 | 154,113,486 | −66 | −4.3e-5 % |
| step15 t1 / t4 | 154,113,552 | 154,113,486 | −66 | −4.3e-5 % |

---

## 3. Affected historical conclusions

Everything below is a **count- or rate-derived** statement. Timing-based conclusions (wall/CPU
times, phase shares, Amdahl fractions) are **not** affected and are left unchanged.

| where | old statement (float-derived) | correction |
|---|---|---|
| **step10** `STEP10_CACHE_SENSITIVITY_REPORT.md` — table column `dist_comp`, and §prose "performs a fixed **10,701,217,792** distance computations (~300 s …)" | count = 10,701,217,792 | count = **14,090,491,387** (the ~300 s / cache comparison / hit-miss / effective-byte conclusions are time- or I/O-based and stand) |
| **step11** `STEP11_HOTSPOT_PROFILE_REPORT.md` §1.2 "`dist_comp` is an accurate proxy for the distance work executed" | accurate proxy | **FALSE** as stated: it under-counts by **24 %** at 1 thread. The uncounted point-to-centroid fraction is ≈0.078 % of the exact count (was ≈0.1 % of the float), still negligible |
| **step11** §1.3 "At `dist_comp = 10.70e9` calls and `compute = 276.91 s`, that is **≈25.9 ns/call**" | 25.9 ns/call | with the exact 14.090e9 calls: **≈19.65 ns/call** (the old figure over-states per-call cost by ~32 %) |
| **step11** §4 "counts match step10 exactly … `dist_comp = 10,701,217,792`" | count = 10,701,217,792 | the *equality* claim still holds (same counter, same partition), but the number is the saturated float; exact = **14,090,491,387** |
| **step11** §5 "contains the `10.70e9` distance calls" | 10.70e9 | **14.09e9** |
| **step11** §6 Amdahl table "distance compute (276.91 s)" | — | **unaffected**: the 96.83 % fraction is `compute` phase wall / search wall (a time share), not `dist_comp` |
| **step7 / step8 / step9** reports — "gate counters `dist_comp=10,701,217,792`" used solely as a *consistency token* | 10,701,217,792 | token should read **14,090,491,387**; the "identical across variants" conclusions still hold |
| **step13** `STEP13_C_INTEGRATION_REPORT.md` — `dist_comp = 10,701,217,792` (1M) and `154,113,552` (100K) | those values | exact **14,090,491,387** / **154,113,486**; the byte-identical-pairs conclusions are output-based and unaffected |
| **REPORT.md** — "join `dist_comp` ~100× (154 M → ~15 G)" | 154 M → ~15 G (≈100×) | exact 154.11e6 → 14.09e9 ⇒ **≈91×**; "~15 G" should read "~14 G" |
| **step12** `STEP12_COMPUTE_REPLAY_REPORT.md` — "candidate counter (`dist_comp` analogue)" | — | **unaffected**: that is the offline replay lab's own counter, not this one |
| **step14** `STEP14_CPU_SCALING_REPORT.md` / `PARALLEL_SAFETY_AUDIT.md` | — | **already correct**: step14 introduced and reported the exact counter (perf table still shows the float column for continuity; the audit already documented the saturation as "D2") |

Net effect on the headline CPU-scaling result: **none.** Step14's scaling ratios and the step15
correctness conclusion are computed from wall/CPU times and the exact counter, not from the float.

---

## 4. Recommendation (already implemented as a diagnostic in step 14)

1. Count distance calls in an **explicit-width unsigned integer**, `uint64_t` (or `size_t` guarded by
   `static_assert(sizeof(size_t) >= 8)`).
2. **Format explicitly** — `std::to_string(uint64_t)` / `PRIu64` — rather than `(size_t)`-casting a
   `float`, which silently prints a truncated saturated value.
3. Keep the `float` only if an approximate, thread-partition-dependent diagnostic is acceptable;
   otherwise remove `dist_comp` or make it `uint64_t`.

The step14 `GATE14_EXACT_COUNT` diagnostic is exactly this and is what the step15 manifest freezes.
