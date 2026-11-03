#!/usr/bin/env python3
"""Gate 4A workload qualification aggregator.

Combines (all previously produced artifacts, nothing recomputed from scratch):
  * GT pair file            (gate3 oracle_pairs.py)
  * found pair dump         (instrumented run, GATE3_PAIR_OUT)
  * task-graph dump         (instrumented run, GATE4A_TASK_OUT)
  * metadata               (build output)
  * dist_comp counter      (from run log, GATE3_INVARIANTS line)

Emits one JSON with the qualification metrics required by Gate 4A:
GT count, GT density, candidate comparisons, comps/GT, TP/FP/FN,
precision/recall, bucket size distribution, task count + degree
distributions, per-vector true-neighbour degree distribution,
invalid candidate comparison fraction (engineering screen >= 5%),
plus the screening verdict under the exploratory band (density in
[0.1%, 20%]).
"""
import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gate3" / "oracle"))
import compare_pairs  # reuse the Gate 3 comparator


def read_meta(path):
    with open(path, "rb") as f:
        raw = f.read()
    n, d, cn, mp = struct.unpack_from("<QQQQ", raw, 0)
    off = 32
    bs = struct.unpack_from("<%dQ" % cn, raw, off); off += 8 * cn
    cent = struct.unpack_from("<%df" % (cn * d), raw, off); off += cn * d * 4
    rad = struct.unpack_from("<%df" % cn, raw, off); off += cn * 4
    assignment = []
    for i in range(cn):
        a = struct.unpack_from("<%dQ" % bs[i], raw, off); off += bs[i] * 8
        assignment.append(a)
    return dict(n=n, d=d, cluster_num=cn, max_points=mp, bucket_sizes=list(bs),
                centroids=cent, radii=list(rad), assignment=assignment)


def dist_summary(xs):
    if not xs:
        return None
    ys = sorted(xs)
    def q(p):
        return ys[min(len(ys) - 1, int(p * (len(ys) - 1) + 0.5))]
    return {"count": len(ys), "min": ys[0], "p25": q(0.25), "p50": q(0.50),
            "p75": q(0.75), "p90": q(0.90), "max": ys[-1],
            "mean": sum(ys) / len(ys)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--fbin", required=True)
    ap.add_argument("--radius", type=float, required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--found", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--log", required=True, help="instrumented run log (for dist_comp)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.fbin, "rb") as f:
        hdr = f.read(8)
        n = struct.unpack("<I", hdr[0:4])[0]
        d = struct.unpack("<I", hdr[4:8])[0]

    gt_list, gt_illegal = compare_pairs.read_pairs(args.gt, n)
    found_list, found_illegal = compare_pairs.read_pairs(args.found, n)
    gt = set(gt_list)
    found = set(found_list)
    tp = len(gt & found)
    fp = len(found - gt)
    fn = len(gt - found)

    m = re.search(r"\[gate3-stat\] dist_comp=(\d+)", Path(args.log).read_text())
    dist_comp = int(m.group(1)) if m else None

    meta = read_meta(args.metadata)
    all_pairs = n * (n - 1) // 2
    density = len(gt) / all_pairs

    # per-vector true-neighbour degrees (from GT)
    deg = [0] * n
    for (a, b) in gt:
        deg[a] += 1
        deg[b] += 1

    # task graph: out-degree per slot, in-degree per bucket
    tasks = {}
    indeg = [0] * meta["cluster_num"]
    edges = 0
    with open(args.tasks) as f:
        for line in f:
            parts = [int(x) for x in line.split()]
            slot, target, dg, neigh = parts[0], parts[1], parts[2], parts[3:]
            tasks[slot] = (target, neigh)
            edges += len(neigh)
            for nc in neigh:
                indeg[nc] += 1

    outdeg = [len(v[1]) for v in tasks.values()]
    self_loops = sum(1 for v in tasks.values() if v[0] in v[1])

    # screening thresholds (exploratory, this project's engineering gate)
    screens = {
        "gt_positive": len(gt) > 0,
        "gt_density_in_0.1_20pct": 0.001 <= density <= 0.20,
        "dist_comp_gt_tp": (dist_comp or 0) > tp,
        "invalid_candidates_ge_5pct": dist_comp is not None and (dist_comp - tp) / dist_comp >= 0.05,
        "both_similar_and_dissimilar_pairs": tp > 0 and (dist_comp or 0) > tp,
    }
    invalid_frac = (dist_comp - tp) / dist_comp if dist_comp else None

    report = {
        "name": args.name, "n": n, "d": d, "radius": args.radius,
        "all_unordered_pairs": all_pairs,
        "gt_pairs": len(gt), "gt_density": density,
        "dist_comp": dist_comp,
        "comps_per_gt": (dist_comp / len(gt)) if dist_comp and gt else None,
        "comps_per_tp": (dist_comp / tp) if dist_comp and tp else None,
        "invalid_candidate_fraction": invalid_frac,
        "TP": tp, "FP": fp, "FN": fn,
        "recall": tp / (tp + fn) if (tp + fn) else None,
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "found_duplicates": len(found_list) - len(found),
        "found_illegal_lines": found_illegal,
        "bucket_size_dist": dist_summary(meta["bucket_sizes"]),
        "bucket_empty": sum(1 for s in meta["bucket_sizes"] if s == 0),
        "bucket_max_points": meta["max_points"],
        "task_edge_count": edges,
        "task_self_loops": self_loops,
        "task_outdeg_dist": dist_summary(outdeg),
        "task_indeg_dist": dist_summary(indeg),
        "true_neighbour_deg_dist": dist_summary(deg),
        "screens": screens,
        "screen_pass": all(screens.values()),
    }
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                     ["name", "gt_pairs", "gt_density", "dist_comp", "comps_per_gt",
                      "invalid_candidate_fraction", "TP", "FP", "FN", "recall",
                      "precision"]}, indent=1))
    print("screens:", json.dumps(screens), "=> PASS" if report["screen_pass"] else "=> FAIL")


if __name__ == "__main__":
    main()
