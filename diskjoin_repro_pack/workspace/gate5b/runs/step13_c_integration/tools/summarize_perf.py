#!/usr/bin/env python3
"""Step 13 — summarise the 6 alternating perf runs (3x A baseline, 3x C).

Both time-reduction % and speed-up ratio are reported (never mixed up).
Reads runs/step13_c_integration/perf/r0*/{stdout,stderr}.log; writes
  runs/step13_c_integration/logs/perf_summary.txt
"""
import os
import re
import glob

BASE = "/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b/runs/step13_c_integration"
P = os.path.join(BASE, "perf")


def parse(d):
    so = open(os.path.join(d, "stdout.log")).read()
    se = open(os.path.join(d, "stderr.log")).read()
    g = {}
    m = re.search(r"\[([0-9.]+) s\] Build done", so);           g["build"] = float(m.group(1)) if m else None
    m = re.search(r"\[([0-9.]+) s\] Join done", so);            g["join_cum"] = float(m.group(1)) if m else None
    m = re.search(r"recall = ([0-9.]+)", so);                   g["recall"] = float(m.group(1)) if m else None
    prof = {m[0]: (m[1], m[2]) for m in
            re.findall(r"\[gate5b-prof\]\s+(\S+)\s+wall_s=([0-9.]+)\s+cpu_s=([0-9.]+)", se)}
    g["search"] = float(prof["SEARCH_TOTAL"][0]) if "SEARCH_TOTAL" in prof else None
    g["compute"] = float(prof["compute"][0]) if "compute" in prof else None
    g["preload"] = float(prof["preload"][0]) if "preload" in prof else None
    m = re.search(r"\[gate3-stat\] dist_comp=(\d+) sampled_count=(\d+) gt=(\d+)", se)
    g["dist_comp"] = int(m.group(1)) if m else None
    g["sampled"] = int(m.group(2)) if m else None
    m = re.search(r"count_only=1 pairs=(\d+)", se) or re.search(r"pairs=(\d+)", se)
    g["pairs"] = int(m.group(1)) if m else None
    m = re.search(r"\[gate4b1-io\] read_calls=(\d+) effective_bytes=(\d+)", se)
    g["read_calls"] = int(m.group(1)) if m else None
    g["eff_bytes"] = int(m.group(2)) if m else None
    m = re.search(r"Elapsed \(wall clock\) time .*?: ([0-9]+):([0-9]+(?:\.[0-9]+)?)", se)
    g["elapsed"] = int(m.group(1)) * 60 + float(m.group(2)) if m else None
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", se)
    g["rss_kb"] = int(m.group(1)) if m else None
    m = re.search(r"User time \(seconds\): ([0-9.]+)", se)
    g["user"] = float(m.group(1)) if m else None
    g["proc"] = (g["build"] + g["search"]) if (g["build"] and g["search"]) else None
    return g


rows = []
for d in sorted(glob.glob(os.path.join(P, "r0*"))):
    label = os.path.basename(d)
    variant = "C" if label.endswith("C") else "A"
    rows.append((label, variant, parse(d)))

lines = []
W = lines.append
W("Step 13 — 1M perf: baseline A (GATE13_C_PATH off) vs C path (on)")
W("Fixed: 10% cache, radius 73984, cluster_num 1000, K 24, error_bound 0.1, gt 8379,")
W("GATE4B0_WINDOW=2, OMP_NUM_THREADS=1, taskset -c 2, pair/trace output OFF.")
W("Order A/C/C/A/A/C. proc = build + search; elapsed = /usr/bin/time wall.")
W("")
hdr = f"{'run':<7}{'var':<4}{'build_s':>9}{'search_s':>10}{'compute_s':>11}{'preload_s':>11}{'proc_s':>9}{'elapsed':>9}{'rss_MiB':>9}{'dist_comp':>14}{'pairs':>12}{'reads':>7}"
W(hdr); W("-" * len(hdr))
for label, variant, g in rows:
    W(f"{label:<7}{variant:<4}{g['build']:>9.3f}{g['search']:>10.3f}{g['compute']:>11.3f}"
      f"{(g['preload'] or 0):>11.3f}{g['proc']:>9.3f}{g['elapsed']:>9.3f}"
      f"{g['rss_kb']/1024:>9.1f}{g['dist_comp']:>14d}{g['pairs']:>12d}{g['read_calls']:>7d}")


def mean(vals):
    return sum(vals) / len(vals) if vals else float("nan")


for key, name in [("build", "build"), ("search", "search"), ("compute", "compute"),
                  ("preload", "preload"), ("proc", "proc(build+search)"),
                  ("elapsed", "elapsed"), ("rss_kb", "RSS_kB")]:
    A = [g[key] for _, v, g in rows if v == "A"]
    C = [g[key] for _, v, g in rows if v == "C"]
    ma, mc = mean(A), mean(C)
    red = (ma - mc) / ma * 100 if ma else float("nan")
    sp = ma / mc if mc else float("nan")
    W(f"mean {name:<16} A={ma:.3f}  C={mc:.3f}   reduction={red:+.2f}%   speedup={sp:.4f}x")

W("")
W("Counts (must match step7 normal): dist_comp=10701217792 sampled_count=7165 pairs=398737742")
W("Reduction %% = (A-C)/A*100 ; Speedup = A/C. Both reported; they are different quantities.")

txt = "\n".join(lines) + "\n"
out = os.path.join(BASE, "logs", "perf_summary.txt")
open(out, "w").write(txt)
print(txt)
