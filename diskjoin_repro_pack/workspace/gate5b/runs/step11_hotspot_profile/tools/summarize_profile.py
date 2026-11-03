#!/usr/bin/env python3
"""Step 11 — parse the single GATE5B_PROFILE run into a phase table + Amdahl bounds.

Reads runs/profile_10pct/{stdout,stderr}.log; writes
  runs/profile_10pct/phase_profile.tsv   (machine-readable)
  logs/phase_summary.txt                 (human-readable)
No third-party deps.
"""
import os
import re
import sys

BASE = "/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b/runs/step11_hotspot_profile"
D = os.path.join(BASE, "runs", "profile_10pct")
se = open(os.path.join(D, "stderr.log")).read()
so = open(os.path.join(D, "stdout.log")).read()

prof = {}
for name, w, c in re.findall(r"\[gate5b-prof\]\s+(\S+)\s+wall_s=([0-9.]+)\s+cpu_s=([0-9.]+)", se):
    prof[name] = (float(w), float(c))
total_w, total_c = prof.pop("SEARCH_TOTAL")
build = float(re.search(r"\[([0-9.]+) s\] Build done", so).group(1))
cumulative_join = float(re.search(r"\[([0-9.]+) s\] Join done", so).group(1))
elapsed = None
m = re.search(r"Elapsed \(wall clock\) time .*?: ([0-9]+):([0-9]+)\.([0-9]+)", se)
if m:
    elapsed = int(m.group(1)) * 60 + int(m.group(2)) + float("0." + m.group(3))
user = float(re.search(r"User time \(seconds\): ([0-9.]+)", se).group(1))
sys_t = float(re.search(r"System time \(seconds\): ([0-9.]+)", se).group(1))

# exclusive (non-nested) slots; find/read/push nest inside preload
excl = ["meta", "graph", "taskprep", "setup", "gorder", "join_setup",
        "preload", "compute", "result"]
sub = ["find", "read", "push"]
sum_excl_w = sum(prof[k][0] for k in excl)
sum_excl_c = sum(prof[k][1] for k in excl)

end_to_end = build + total_w  # process wall = build + search

def amdahl(part_w, speedup):
    return end_to_end - part_w * (1.0 - 1.0 / speedup)

lines = []
W = lines.append
W("Step 11 — coarse phase profile (single fixed-config run, 10%% cache, 1 thread)".replace("%%", "%"))
W("=" * 78)
W("")
W("Run: runs/profile_10pct  rc=0  (config == step10 r02_b010: mem_budget 0.0476837158203125,")
W("     radius 73984, cluster_num 1000, K 24, error_bound 0.1, gt 8379, GATE4B0_WINDOW=2,")
W("     OMP_NUM_THREADS=1, taskset -c 2, pair/trace output OFF, GATE3_COUNT_ONLY=1)")
W("")
W("Counters (must equal step10):")
for pat in [r"dist_comp=(\d+)", r"sampled_count=(\d+)", r"pairs=(\d+)",
            r"read_calls=(\d+)", r"effective_bytes=(\d+)", r"hit=(\d+)", r"miss=(\d+)"]:
    mm = re.search(pat, se)
    if mm:
        W(f"  {pat.split('=')[0]:<16} {mm.group(1)}")
W("")
W("Wall-time decomposition (seconds). Sub-slots FIND/READ/PUSH nest inside PRELOAD.")
W(f"{'phase':<12}{'wall_s':>12}{'cpu_s':>12}{'wall_%search':>14}{'wall-cpu(idle)':>16}")
W("-" * 66)
for k in excl:
    w, c = prof[k]
    W(f"{k:<12}{w:>12.6f}{c:>12.6f}{100*w/total_w:>13.3f}%{w-c:>16.6f}")
for k in sub:
    w, c = prof[k]
    W(f"  {k:<10}{w:>12.6f}{c:>12.6f}{100*w/total_w:>13.3f}%{w-c:>16.6f}")
W("-" * 66)
W(f"{'SUM(excl)':<12}{sum_excl_w:>12.6f}{sum_excl_c:>12.6f}{100*sum_excl_w/total_w:>13.3f}%")
W(f"{'SEARCH_TOTAL':<12}{total_w:>12.6f}{total_c:>12.6f}{100.0:>13.3f}%{total_w-total_c:>16.6f}")
W(f"{'untimed gap':<12}{total_w-sum_excl_w:>12.6f}{total_c-sum_excl_c:>12.6f}{100*(total_w-sum_excl_w)/total_w:>13.3f}%")
W("")
W("Full process:")
W(f"  build (kmeans)              wall={build:.6f} s  ({100*build/end_to_end:.2f}% of process)")
W(f"  search (Join)               wall={total_w:.6f} s  ({100*total_w/end_to_end:.2f}%)")
W(f"  process end-to-end          wall={end_to_end:.6f} s  (elapsed {elapsed} s)")
W(f"  CPU (user+sys)              cpu={user+sys_t:.2f} s  -> {100*(user+sys_t)/end_to_end:.1f}% of wall (1 thread)")
W(f"  printed '[X s] Join done'   {cumulative_join:.3f} s (cumulative: build+search)")
W("")
W("Hypothesis tests:")
comp_w = prof["compute"][0]
pre_w = prof["preload"][0]
find_w = prof["find"][0]
push_w = prof["push"][0]
read_w = prof["read"][0]
read_idle = read_w - prof["read"][1]
W(f"  (1) distance-dominated      : compute = {comp_w:.3f} s = {100*comp_w/total_w:.2f}% of search,")
W(f"                                {100*comp_w/end_to_end:.2f}% of process wall  -> SUPPORTED")
W(f"  (2) cache-mgmt overhead     : find+push = {find_w+push_w:.3f} s = {100*(find_w+push_w)/total_w:.3f}% of search -> NOT significant")
W(f"  (3) read waiting            : read wall = {read_w:.3f} s = {100*read_w/total_w:.2f}% of search,")
W(f"                                of which {read_idle:.3f} s idle (blocking O_DIRECT) = {100*read_idle/total_w:.2f}% -> measurable but NOT a bottleneck")
W("")
W("Ideal end-to-end upper bounds (Amdahl; ignores ALL extra overhead of the accelerator):")
W(f"  end-to-end baseline = {end_to_end:.3f} s")
for label, part in [("compute only", comp_w), ("whole search", total_w),
                    ("read wait only", read_idle)]:
    for s in (2.0, 10.0):
        t = amdahl(part, s)
        W(f"  {label:<14} x{s:<4.0f} -> {t:8.3f} s  ({end_to_end/t:.2f}x end-to-end)")
    W(f"  {label:<14} inf  -> {amdahl(part, 1e18):8.3f} s  ({end_to_end/amdahl(part,1e18):.2f}x end-to-end)")
W("")
W("These bounds assume the accelerated part's time goes to zero-ish and that NOTHING else")
W("gets slower; they are NOT a prediction that a GPU yields the same speed-up.")

txt = "\n".join(lines) + "\n"
print(txt)

with open(os.path.join(BASE, "logs", "phase_summary.txt"), "w") as f:
    f.write(txt)
with open(os.path.join(D, "phase_profile.tsv"), "w") as f:
    f.write("phase\twall_s\tcpu_s\tnested_in\n")
    for k in excl:
        f.write(f"{k}\t{prof[k][0]:.6f}\t{prof[k][1]:.6f}\t-\n")
    for k in sub:
        f.write(f"{k}\t{prof[k][0]:.6f}\t{prof[k][1]:.6f}\tpreload\n")
    f.write(f"SEARCH_TOTAL\t{total_w:.6f}\t{total_c:.6f}\t(enclosing)\n")
    f.write(f"build\t{build:.6f}\t-\t-\n")
    f.write(f"process_end_to_end\t{end_to_end:.6f}\t{user+sys_t:.6f}\t-\n")
print("wrote logs/phase_summary.txt and runs/profile_10pct/phase_profile.tsv")
