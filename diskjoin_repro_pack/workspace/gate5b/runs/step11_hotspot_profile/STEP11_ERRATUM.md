# Step 11 — Erratum (scope corrections)

Date: 2026-11-03 · HEAD: `980bc3956dd2f16f5f521783f7314430262a9966`
Applies to: `STEP11_HOTSPOT_PROFILE_REPORT.md` (that report is **preserved unchanged**; this file corrects scope only).

This erratum does **not** change any measured number in the step11 report. It corrects three
**scope/labelling** statements that could otherwise be over-read near a GPU/accelerator decision.
All step11 raw evidence (`runs/profile_10pct/`, `logs/`) and the step11 patch are untouched.

---

## Correction 1 — 96.83 % is the **whole `compute` phase**, not the pure distance kernel

The step11 headline "distance computation dominates … `compute` = 276.91 s = **96.83 %** of search"
is correct as a *phase* statement, but the label "distance computation" over-states the resolution.
`compute` is the **whole `#pragma omp parallel for` region** and contains, per pair:

- the `dist_l2(vec1, vec2, &d)` call (indirect, out-of-line AVX-512 kernel) — **`lib/DiskJoin.h:350–351` / `:365–366`**;
- the **pruning/branch**: `if (dist < epsilon*epsilon)` and the `id2 >= id1` upper-triangle filter;
- the **result handling**: `dist_comp++`, the pair counters and the (count-only) sink.

So **96.83 % = distance + pruning/branch + result handling**, not the bare distance arithmetic.
The step11 report already says this in §3.2 ("the AVX-512 kernel body, the indirect-call overhead,
the loop and the result handling are **inseparable**") and §9 ("the `compute` figure is the whole
parallel-for region … not the bare distance arithmetic"), but the executive summary and
"Bottom line" phrase it as "distance computation dominates" / "distance-dominated". Those phrases
must be read as **"the compute phase dominates"**.

Splitting the 96.83 % into (i) AVX-512 arithmetic, (ii) indirect-call overhead, and (iii)
pruning/branch + result handling is **not possible from step11** (see √Correction 2 and the step12
replay below), because no PMU sampling was available.

## Correction 2 — the Amdahl numbers refer to the **whole `compute` phase**

The Amdahl table in §6 keeps its arithmetic, but its row label "distance compute (276.91 s)" is
renamed to **"`compute` phase (276.91 s)"**. The speed-up bounds apply to accelerating the **entire
compute phase** (distance + prune + result handling), because that is the measured fraction
`f`. They are **not** a bound on accelerating only the distance kernel: if part of the 276.91 s is
irreducible branch/result work, accelerating "the distance kernel" alone would move a smaller
fraction and yield **less** speed-up than the table shows. No number in the table changes; only its
scope label is corrected.

## Correction 3 — wall−CPU is a **non-CPU-time estimate**, not all SSD wait

The step11 report records the wall−CPU gap per phase and, for `preload`, attributes **7.10 s** to
"idle device wait" in `O_DIRECT` `read(2)`. This erratum sharpens the general claim:

- A **wall−CPU gap is only an estimate of time the thread was not executing on-CPU** (blocking
  syscalls, scheduling, I/O wait, etc.). It is **not** a direct measurement of SSD latency, and it
  is **not** proved to be entirely storage wait.
- For `preload` specifically, the `read` sub-phase is a **serial** loop around `posixDirectReadCluster`,
  so the 7.10 s gap is **consistent with** blocking O_DIRECT reads (and the effective bandwidth
  ≈ 317 MB/s is physically plausible), but the step11 instrumentation cannot *prove* that every
  one of those 7.10 s is device wait versus e.g. scheduler delay.
- For `compute`, wall−CPU is **0.026 s** — negligible either way, so the compute phase is
  CPU-bound regardless of how the small gap is attributed.

Where the step11 report says the gap "isolates blocking waits" or "attributes device wait", read it
as **"estimates non-CPU time"**; the SSD attribution for `read` remains the most plausible reading
but is an inference, not a measurement.

---

## Net effect on conclusions

None of the corrections reverse a step11 finding:

1. The **compute phase** is still the overwhelming hotspot (96.83 % of search, CPU-bound).
2. Cache management (`find+push` = 0.33 %) and read waiting (≤ 2.73 %, mostly non-CPU) remain
   non-bottlenecks.
3. The Amdahl bounds stand **for the whole compute phase**; they are upper bounds only and carry
   the same accelerator-overhead caveats as before.

What changes is only the **finer scope language**: 96.83 % is not a pure-distance-kernel share, and
the wall−CPU gap is a non-CPU-time estimate rather than a proven SSD-wait measurement. The step12
`STEP12_COMPUTE_REPLAY_REPORT.md` provides the first *measured separation* of the indirect-call and
batching/operand-reuse parts (on a bounded task replay), which is what step11 could not do without
PMU access.
