#!/usr/bin/env python3
"""Step 14 — summarise 1M compute-thread scaling (1/2/4 threads, 3 runs each).

Reads runs/step14_cpu_scaling/perf/r*/{stdout,stderr}.log and writes
  runs/step14_cpu_scaling/logs/perf_summary.txt

Denominator for every speed-up is THIS round's C single-thread mean (never an
old run). Both time-reduction %% and speed-up are reported separately.
"""
import os, re, glob

BASE = "/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b/runs/step14_cpu_scaling"
P = os.path.join(BASE, "perf")

RE = {
    "threads":   re.compile(r"\[gate3\] count_only=1 pairs=(\d+) threads=(\d+)"),
    "pairs":     re.compile(r"\[gate3\] count_only=1 pairs=(\d+) threads="),
    "stat":      re.compile(r"\[gate3-stat\] dist_comp=(\d+) sampled_count=(\d+) gt=(\d+)"),
    "exact":     re.compile(r"\[gate14-exact\] dist_comp_exact=(\d+)"),
    "io":        re.compile(r"\[gate4b1-io\] read_calls=(\d+) effective_bytes=(\d+) requested_aligned_bytes=(\d+)"),
    "cache":     re.compile(r"\[gate4a-cache\] capacity_slots=(\d+) length=(\d+) budget_bytes=(\d+) filled=(\d+) total=(\d+) hit=(\d+) miss=(\d+) admit=(\d+) evict=(\d+) reject=(\d+)"),
    "elapsed":   re.compile(r"Elapsed \(wall clock\) time .*?: (\d+):([0-9]+(?:\.[0-9]+)?)"),
    "rss":       re.compile(r"Maximum resident set size \(kbytes\): (\d+)"),
    "user":      re.compile(r"User time \(seconds\): ([0-9.]+)"),
    "sys":       re.compile(r"System time \(seconds\): ([0-9.]+)"),
    "pctcpu":    re.compile(r"Percent of CPU this job got: (\d+)%"),
    "aff":       re.compile(r"level \d+ thread 0x[0-9a-f]+ affinity (\d+)"),
}
PROF = re.compile(r"\[gate5b-prof\]\s+(\S+)\s+wall_s=([0-9.]+)\s+cpu_s=([0-9.]+)")


def parse(d):
    so = open(os.path.join(d, "stdout.log")).read()
    se = open(os.path.join(d, "stderr.log")).read()
    g = {}
    prof = {m[0]: (float(m[1]), float(m[2])) for m in PROF.findall(se)}
    for ph in ("taskprep", "preload", "compute", "SEARCH_TOTAL"):
        g[ph + "_w"] = prof.get(ph, (None, None))[0]
        g[ph + "_c"] = prof.get(ph, (None, None))[1]
    for k, rx in RE.items():
        m = rx.search(se) or rx.search(so)
        if k == "aff":
            g["aff"] = ",".join(rx.findall(se))
        elif k == "threads":
            g["threads"] = int(m.group(2)) if m else None
            g["pairs"] = int(m.group(1)) if m else None
        elif k == "stat":
            g["dist_comp"], g["sampled"], g["gt"] = map(int, m.groups()) if m else (None, None, None)
        elif k == "io":
            g["read_calls"], g["eff_bytes"], g["req_bytes"] = map(int, m.groups()) if m else (None, None, None)
        elif k == "cache":
            g["cap_slots"], g["filled"] = (int(m.group(1)), int(m.group(4))) if m else (None, None)
        elif k == "elapsed":
            g["elapsed"] = int(m.group(1)) * 60 + float(m.group(2)) if m else None
        elif k == "rss":
            g["rss_mb"] = int(m.group(1)) / 1024.0 if m else None
        elif k == "user":
            g["user"] = float(m.group(1)) if m else None
        elif k == "sys":
            g["sys"] = float(m.group(1)) if m else None
        elif k == "pctcpu":
            g["pctcpu"] = int(m.group(1)) if m else None
        else:
            g[k] = int(m.group(1)) if m else None
    return g


rows = []
for d in sorted(glob.glob(os.path.join(P, "r*"))):
    label = os.path.basename(d)
    m = re.match(r"r(\d+)_t(\d+)", label)
    t = int(m.group(2)) if m else None
    rows.append((label, t, parse(d)))

lines = []
W = lines.append
W("Step 14 — BigANN1M C-path compute-thread scaling (1/2/4 threads)")
W("Fixed: GATE13_C_PATH=1, radius 73984, cluster_num 1000, K 24, error_bound 0.1, gt 8379,")
W("GATE4B0_WINDOW=2, 10% cache, GATE14_SKIP_BUILD=1 (fixed verified graph reused),")
W("pair/trace output OFF (GATE3_COUNT_ONLY). Build time excluded (skipped) — see build_1thread.")
W("Nested physical core sets {2}/{2,3}/{2,3,4,5}; OMP_PROC_BIND=true; rotation 1/2/4,2/4/1,4/1/2.")
W("")

hdr = (f"{'run':<8}{'t':>2}{'cpu':>6}{'compute_w':>10}{'compute_c':>10}{'search_w':>9}"
       f"{'search_c':>9}{'preload_w':>10}{'tasks_w':>8}{'elapsed':>8}{'CPU%':>6}{'rss_MB':>7}"
       f"{'exact':>14}{'dist_f':>13}{'sampled':>8}{'pairs':>12}{'eff_GB':>8}{'cacheslots':>11}")
W(hdr); W("-" * len(hdr))
for label, t, g in rows:
    W(f"{label:<8}{t:>2}{(g.get('aff') or ''):>6}{g['compute_w']:>10.3f}{g['compute_c']:>10.3f}"
      f"{g['SEARCH_TOTAL_w']:>9.3f}{g['SEARCH_TOTAL_c']:>9.3f}{(g['preload_w'] or 0):>10.3f}"
      f"{(g['taskprep_w'] or 0):>8.3f}{g['elapsed']:>8.2f}{g['pctcpu']:>6}{g['rss_mb']:>7.1f}"
      f"{g['exact']:>14}{g['dist_comp']:>13}{g['sampled']:>8}{g['pairs']:>12}"
      f"{(g['eff_bytes'] or 0)/1e9:>8.3f}{g['cap_slots']:>11}")


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else float("nan")


tvals = sorted({t for _, t, _ in rows})
means = {t: {k: mean([g[k] for _, tt, g in rows if tt == t]) for k in
             ("compute_w", "compute_c", "SEARCH_TOTAL_w", "SEARCH_TOTAL_c", "preload_w", "taskprep_w", "elapsed")}
         for t in tvals}

W("")
W("Means per thread count (denominator = this round's C single-thread mean):")
W(f"{'threads':>8}{'compute_w':>11}{'search_w':>10}{'elapsed_w':>11}{'CPU%':>7}"
  f"{'speedup_compute':>16}{'eff_compute':>12}{'speedup_search':>15}{'eff_search':>11}{'speedup_proc':>13}{'eff_proc':>10}")
base_c = means[1]["compute_w"]; base_s = means[1]["SEARCH_TOTAL_w"]; base_e = means[1]["elapsed"]
for t in tvals:
    sc = base_c / means[t]["compute_w"]; es = base_s / means[t]["SEARCH_TOTAL_w"]; ep = base_e / means[t]["elapsed"]
    W(f"{t:>8}{means[t]['compute_w']:>11.3f}{means[t]['SEARCH_TOTAL_w']:>10.3f}{means[t]['elapsed']:>11.2f}"
      f"{'':>7}{sc:>16.3f}{sc/t:>12.3f}{es:>15.3f}{es/t:>11.3f}{ep:>13.3f}{ep/t:>10.3f}")

W("")
W("Counts (all runs must agree): pairs=398737742 sampled_count=7165; exact distance count must")
W("be identical across thread counts (float dist_comp is approximate by construction — see audit D2).")
W("exact_count per run: " + ", ".join(f"t{tt}={int(mean([g['exact'] for _,t,g in rows if t==tt]))}" for tt in tvals))
W("pctCPU here is /usr/bin/time process average; not used for efficiency numerators.")

txt = "\n".join(lines) + "\n"
open(os.path.join(BASE, "logs", "perf_summary.txt"), "w").write(txt)
print(txt)
