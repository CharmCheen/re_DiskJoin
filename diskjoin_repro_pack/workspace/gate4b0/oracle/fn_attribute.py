#!/usr/bin/env python3
"""Gate 4B-0 Task 1: exact FN (false-negative) attribution for P1/P3.

For every ground-truth pair that the join did NOT output, map it to its
bucket pair and classify it into six mutually exclusive categories:

  1  same bucket pair            (both vectors in one bucket; self-join
                                  computes every within-bucket pair, so a
                                  non-empty class 1 indicates an oracle/join
                                  mismatch - a correctness signal)
  2  cross bucket, final task graph contains the bucket edge
                                 (cross-join computes ALL pairs of the two
                                  buckets with no ID filter, so a non-empty
                                  class 2 is a potential correctness issue)
  3  neither direction of the bucket pair appears in the candidate top-K
                                  (KNN of neither centre reaches the other)
  4  only the REVERSE direction appears in the top-K; dropped by the
                                  upper-triangle filter (i <= neighbour)
  5  forward (upper-triangle-compatible) candidate exists but was pruned
                                  by Algorithm 3 (error-bound pruning)
  6  unexplained (defensive; must be 0)

Semantics recap (from lib/DiskJoin.h):
  * candidate graph: knnSearchBaseLayer(i, K) over the centre HNSW graph,
    dumped by GATE4A_KNN_OUT pre-sort/pre-prune: "i deg (dist/2 neighbour)*"
  * pruning loop keeps [0..ptr] (near end) after accumulating arcos from the
    FAR end until the sum reaches error_bound
  * upper-triangle filter keeps neighbour j of bucket i iff i <= j
  * cross-join: for edge (a -> b), ALL (id1 in a, id2 in b) pairs computed
  * self-join: ALL within-bucket pairs (id2 < id1)

Everything here is read-only w.r.t. gate4a/gate4b0 artefacts.
"""
import array
import json
import math
import struct
import sys
from pathlib import Path

WS = Path("/home/qch/DiskJoin/diskjoin_repro_pack/workspace")
G4A = WS / "gate4a"
G4B0 = WS / "gate4b0"

DATASETS = {
    "p1": {
        "metadata": G4A / "data/p1.metadata",
        "knn": G4B0 / "runs/p1_default/knn.txt",
        "tasks_eb0.1": G4B0 / "runs/p1_default/tasks.txt",
        "tasks_eb1.0": G4A / "runs/tasks_p1_eb1.0.txt",
        "gt": G4A / "runs/gt_p1.txt",
        "found_eb0.1": G4B0 / "runs/p1_default/pairs.txt",
        "found_eb1.0": G4A / "runs/pairs_p1_eb1.0.txt",
    },
    "p3": {
        "metadata": G4A / "data/p3.metadata",
        "knn": G4B0 / "runs/p3_default/knn.txt",
        "tasks_eb0.1": G4B0 / "runs/p3_default/tasks.txt",
        "tasks_eb1.0": G4B0 / "runs/p3_eb1.0_small_dumps/tasks.txt",
        "gt": G4A / "runs/gt_p3.txt",
        "found_eb0.1": G4B0 / "runs/p3_default/pairs.txt",
        "found_eb1.0": G4A / "runs/pairs_p3_eb1.0.txt",
    },
}

INF = float("inf")


def parse_metadata(path):
    with open(path, "rb") as f:
        data = f.read()
    off = 0
    n, d, cluster_num, max_points = struct.unpack_from("<4Q", data, off)
    off += 32
    bucket_sizes = list(struct.unpack_from(f"<{cluster_num}Q", data, off))
    off += 8 * cluster_num
    off += 4 * d * cluster_num          # centroids (unused here)
    off += 4 * cluster_num              # radii (unused here)
    id2bucket = [0] * n
    for b in range(cluster_num):
        ids = struct.unpack_from(f"<{bucket_sizes[b]}Q", data, off)
        off += 8 * bucket_sizes[b]
        for i in ids:
            id2bucket[i] = b
    assert off <= len(data), f"metadata overrun: {off} > {len(data)}"
    assert sorted(id2bucket) == list(range(n)) or set(id2bucket) <= set(range(cluster_num))
    return {"n": n, "d": d, "cluster_num": cluster_num,
            "bucket_sizes": bucket_sizes, "id2bucket": id2bucket}


def parse_knn(path):
    """Return {bucket: [(dist/2, neighbour), ...]} in dump order (descending
    distance) and the per-bucket candidate label multiset."""
    cand = {}
    dup_labels = 0
    with open(path) as f:
        for line in f:
            parts = [x for x in line.split()]
            i = int(parts[0])
            deg = int(parts[1])
            vals = parts[2:]
            assert len(vals) == 2 * deg, f"knn degree mismatch bucket {i}"
            entries = []
            for k in range(deg):
                dist = float(vals[2 * k])
                nb = int(vals[2 * k + 1])
                entries.append((dist, nb))
            if len({nb for _, nb in entries}) != deg:
                dup_labels += 1
            cand[i] = entries
    return cand, dup_labels


def parse_tasks(path):
    """Return {target_bucket: [neighbour, ...]} reconstructed from the slot
    dump 'slot order[slot] deg neighbours...' (only the target's own list
    matters; slot placement is order-dependent, content is not)."""
    tasks = {}
    with open(path) as f:
        for line in f:
            parts = [int(x) for x in line.split()]
            slot, target, deg = parts[0], parts[1], parts[2]
            neigh = parts[3:3 + deg]
            tasks[target] = neigh
    return tasks


def read_pairs(path):
    pairs = set()
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                u, v = int(parts[0]), int(parts[1])
                pairs.add((u, v) if u < v else (v, u))
    return pairs


def final_edges(tasks):
    """Directed edges (a -> b), b != a, present in the final task graph."""
    edges = set()
    dup_nonhead = 0
    for target, neigh in tasks.items():
        seen = set()
        for nb in neigh:
            if nb == target:
                continue
            if nb in seen:
                dup_nonhead += 1
            seen.add(nb)
            edges.add((target, nb))
    return edges, dup_nonhead


def covered_pairs(tasks, meta):
    """Every unordered vector pair the join semantics computes: all
    within-bucket pairs plus, for every final edge (a -> b), all cross pairs.
    Used to prove found == coverage (hence class 2 must be empty)."""
    cov = set()
    sizes = meta["bucket_sizes"]
    id2b = meta["id2bucket"]
    # within-bucket pairs
    by_bucket = [[] for _ in range(meta["cluster_num"])]
    for i, b in enumerate(id2b):
        by_bucket[b].append(i)
    for ids in by_bucket:
        L = len(ids)
        for x in range(L):
            ux = ids[x]
            for y in range(x + 1, L):
                cov.add((ux, ids[y]))
    # cross pairs per final edge
    for target, neigh in tasks.items():
        for nb in neigh:
            if nb == target:
                continue
            for u in by_bucket[target]:
                for v in by_bucket[nb]:
                    cov.add((u, v) if u < v else (v, u))
    return cov


def classify(ds_name, eb):
    spec = DATASETS[ds_name]
    meta = parse_metadata(spec["metadata"])
    cand, dup_labels = parse_knn(spec["knn"])
    tasks = parse_tasks(spec[f"tasks_eb{eb}"])
    gt = read_pairs(spec["gt"])
    found = read_pairs(spec[f"found_eb{eb}"])

    edges, dup_nonhead = final_edges(tasks)
    cand_set = {b: {nb for _, nb in lst} for b, lst in cand.items()}

    # ---- sanity: found set vs join coverage ----
    # every pair the join semantics computes = coverage; the join outputs
    # exactly coverage AND dist < eps^2. So: found MUST be a subset of
    # coverage, and (coverage AND GT) - found may only contain pairs where
    # the C++ float32 distance test disagrees with the double-precision
    # oracle at the eps^2 boundary (analysed separately).
    cov = covered_pairs(tasks, meta)
    found_outside_coverage = found - cov
    uncovered_gt = (cov & gt) - found
    fp = found - gt

    fn = gt - found
    tp = gt & found
    assert len(gt) == len(tp) + len(fn)
    assert not fp

    classes = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}
    id2b = meta["id2bucket"]
    sizes = meta["bucket_sizes"]
    for (u, v) in fn:
        bu, bv = id2b[u], id2b[v]
        if bu == bv:
            cls = 1
        else:
            a, b = (bu, bv) if bu < bv else (bv, bu)
            if (a, b) in edges:
                cls = 2
            elif b in cand_set.get(a, set()):
                cls = 5
            elif a in cand_set.get(b, set()):
                cls = 4
            else:
                cls = 3
        classes[cls].append((u, v))

    # defensive class 6: everything above is exhaustive, so it must be empty
    total = sum(len(c) for c in classes.values())
    assert total == len(fn), f"{ds_name} eb{eb}: {total} != {len(fn)}"

    # per-class bucket-pair view
    bp = {}
    for cls in range(1, 7):
        pairs = classes[cls]
        bsets = {}
        for (u, v) in pairs:
            key = (id2b[u], id2b[v])
            key = (key[0], key[1]) if key[0] <= key[1] else (key[1], key[0])
            bsets[key] = bsets.get(key, 0) + 1
        bp[cls] = bsets

    # sample records (max 3 per class) with context
    samples = {}
    for cls in range(1, 7):
        recs = []
        for (u, v) in classes[cls][:3]:
            bu, bv = id2b[u], id2b[v]
            a, b = (bu, bv) if bu < bv else (bv, bu)
            fwd = None
            for dist, nb in cand.get(a, []):
                if nb == b:
                    fwd = dist
                    break
            rev = None
            for dist, nb in cand.get(b, []):
                if nb == a:
                    rev = dist
                    break
            recs.append({"pair": [u, v], "buckets": [bu, bv],
                         "bucket_sizes": [sizes[bu], sizes[bv]],
                         "cand_fwd_dist_half": fwd, "cand_rev_dist_half": rev,
                         "edge_in_final_graph": (a, b) in edges})
        samples[cls] = recs

    return {
        "eb": eb,
        "gt": len(gt),
        "tp": len(tp),
        "fn": len(fn),
        "fp": len(fp),
        "found_outside_coverage": len(found_outside_coverage),
        "uncovered_gt_pairs": len(uncovered_gt),
        "coverage_pairs": len(cov),
        "knn_dup_labels": dup_labels,
        "tasks_dup_nonhead": dup_nonhead,
        "final_edge_count": len(edges),
        "class_counts": {cls: len(classes[cls]) for cls in classes},
        "class_frac": {cls: (len(classes[cls]) / len(fn) if fn else 0.0)
                       for cls in classes},
        "class_bucket_pairs": {cls: len(bp[cls]) for cls in bp},
        "class_bucket_pair_examples": {cls: sorted(bp[cls].items(),
                                                   key=lambda kv: -kv[1])[:8]
                                       for cls in bp},
        "samples": samples,
        "_boundary_pairs": classes[1] + classes[2],
        "_uncovered_gt": sorted(uncovered_gt),
        "_found_outside_coverage": sorted(found_outside_coverage),
    }, classes, edges, cand_set


def f32(x):
    """Round a Python float to float32 (nearest-even via struct pack)."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def read_fbin(path):
    with open(path, "rb") as f:
        hdr = f.read(8)
        n = int.from_bytes(hdr[0:4], "little")
        d = int.from_bytes(hdr[4:8], "little")
        flat = array.array("f")
        flat.frombytes(f.read(n * d * 4))
    return n, d, flat


def sq_l2_double(va, vb):
    """Same convention as the gate3 oracle: double accumulation."""
    s = 0.0
    for x, y in zip(va, vb):
        dx = x - y
        s += dx * dx
    return s


def sq_l2_f32sim(va, vb):
    """Sequential float32 accumulation (approximates the AVX2 FMA lane sum;
    not bit-exact - the double deviation from the threshold is the decisive
    boundary-tie metric)."""
    s = 0.0
    for x, y in zip(va, vb):
        dx = f32(x - y)
        s = f32(s + f32(dx * dx))
    return s


def boundary_analysis(ds_name, pairs, radius=0.2, tol=1e-4):
    """For GT pairs the join semantics covers (same bucket or covered bucket
    edge) but did not output: quantify how far their squared L2 sits from the
    eps^2 boundary. Oracle (double, threshold=radius as parsed) vs join
    (float32 FMA, threshold = (float)sqrt((float)radius)^2)."""
    spec = DATASETS[ds_name]
    n, d, flat = read_fbin(G4A / f"data/{ds_name}.fbin")
    r32 = f32(radius)
    eps32 = f32(math.sqrt(r32))
    thr32 = f32(eps32 * eps32)
    recs = []
    boundary_ok = True
    for (u, v) in pairs:
        va = flat[u * d:(u + 1) * d]
        vb = flat[v * d:(v + 1) * d]
        dist_d = sq_l2_double(va, vb)
        dist_f = sq_l2_f32sim(va, vb)
        rel = abs(dist_d - radius) / radius
        # oracle says GT (dist_d < radius); join must reject on the float side
        rec = {"pair": [u, v], "dist2_double": dist_d,
               "dist2_f32sim": dist_f, "thr_double": radius, "thr_f32": thr32,
               "rel_dev_from_boundary": rel,
               "oracle_in": dist_d < radius,
               "f32sim_rejects": not (dist_f < thr32)}
        recs.append(rec)
        if rel >= tol or not rec["oracle_in"]:
            boundary_ok = False
    return {"threshold_f32": thr32, "tol": tol, "pairs": recs,
            "all_boundary_ties": boundary_ok}


def incremental(ds_name):
    """eb=1.0 vs eb=0.1: isolate FN pairs newly introduced by Algorithm 3
    pruning at the larger error bound, and map them to dropped edges."""
    spec = DATASETS[ds_name]
    meta = parse_metadata(spec["metadata"])
    id2b = meta["id2bucket"]
    gt = read_pairs(spec["gt"])
    f01 = read_pairs(spec["found_eb0.1"])
    f10 = read_pairs(spec["found_eb1.0"])
    t01 = parse_tasks(spec["tasks_eb0.1"])
    t10 = parse_tasks(spec["tasks_eb1.0"])
    e01, _ = final_edges(t01)
    e10, _ = final_edges(t10)

    fn01 = gt - f01
    fn10 = gt - f10
    inc = fn10 - fn01           # newly lost at eb=1.0
    rec = fn01 - fn10           # recovered at eb=1.0 (must be empty)
    dropped_edges = e01 - e10   # edges pruned away by larger eb
    added_edges = e10 - e01     # must be empty (pruning only removes)

    # every incremental FN pair must sit on a dropped edge
    on_dropped = 0
    not_on_dropped = []
    inc_bucket_pairs = {}
    for (u, v) in inc:
        bu, bv = id2b[u], id2b[v]
        a, b = (bu, bv) if bu < bv else (bv, bu)
        if (a, b) in dropped_edges:
            on_dropped += 1
        else:
            not_on_dropped.append((u, v, a, b))
        inc_bucket_pairs[(a, b)] = inc_bucket_pairs.get((a, b), 0) + 1

    # GT pairs lost per dropped edge
    per_edge_gt = {}
    for (a, b), cnt in inc_bucket_pairs.items():
        per_edge_gt[f"{a}->{b}"] = cnt

    return {
        "fn_eb0.1": len(fn01),
        "fn_eb1.0": len(fn10),
        "incremental_fn": len(inc),
        "recovered_fn": len(rec),
        "edges_eb0.1": len(e01),
        "edges_eb1.0": len(e10),
        "dropped_edges": len(dropped_edges),
        "added_edges": len(added_edges),
        "incremental_on_dropped_edges": on_dropped,
        "incremental_not_on_dropped": len(not_on_dropped),
        "not_on_dropped_examples": not_on_dropped[:5],
        "dropped_edge_list": sorted(dropped_edges),
        "gt_pairs_per_dropped_edge_top": sorted(per_edge_gt.items(),
                                                key=lambda kv: -kv[1])[:10],
    }


def main():
    out = {}
    ok_all = True
    for ds in ("p1", "p3"):
        ds_out = {}
        for eb in ("0.1", "1.0"):
            res, classes, _, _ = classify(ds, eb)
            # class1+class2 (covered FN) must equal (coverage AND GT) - found
            covered_fn = set(classes[1]) | set(classes[2])
            uncovered_gt = set(res.pop("_uncovered_gt"))
            foc = res.pop("_found_outside_coverage")
            bpairs = res.pop("_boundary_pairs")
            assert covered_fn == uncovered_gt, \
                f"{ds} eb{eb}: covered FN {len(covered_fn)} != uncovered GT {len(uncovered_gt)}"
            assert len(foc) == 0, f"{ds} eb{eb}: found pairs outside join coverage!"
            # boundary analysis for covered-but-missing GT pairs
            if bpairs:
                bres = boundary_analysis(ds, bpairs)
                res["boundary_analysis"] = bres
                if not bres["all_boundary_ties"]:
                    ok_all = False
            else:
                res["boundary_analysis"] = {"all_boundary_ties": True,
                                            "pairs": [], "note": "no covered FN"}
            ds_out[f"eb{eb}"] = res
            cc = res["class_counts"]
            print(f"[{ds} eb={eb}] GT={res['gt']} TP={res['tp']} FN={res['fn']} "
                  f"FP={res['fp']} covered_FN={len(covered_fn)} "
                  f"(boundary_ties="
                  f"{res['boundary_analysis'].get('all_boundary_ties')}) "
                  f"edges={res['final_edge_count']}")
            print(f"    class1(same-bucket)={cc[1]} class2(edge-covered)={cc[2]} "
                  f"class3(no-topK)={cc[3]} class4(reverse-only)={cc[4]} "
                  f"class5(alg3-pruned)={cc[5]} class6(unexplained)={cc[6]}")
            if cc[6] != 0 or res["found_outside_coverage"] != 0:
                ok_all = False
            # class1/2 nonzero is acceptable ONLY if every such pair is an
            # eps^2 boundary tie (float32 join vs double oracle)
            if (cc[1] + cc[2]) > 0 and not res["boundary_analysis"]["all_boundary_ties"]:
                ok_all = False
        inc = incremental(ds)
        ds_out["incremental"] = inc
        print(f"[{ds} incremental] fn0.1={inc['fn_eb0.1']} fn1.0={inc['fn_eb1.0']} "
              f"inc={inc['incremental_fn']} recovered={inc['recovered_fn']} "
              f"dropped_edges={inc['dropped_edges']} "
              f"on_dropped={inc['incremental_on_dropped_edges']} "
              f"not_on_dropped={inc['incremental_not_on_dropped']}")
        if (inc["incremental_fn"] != inc["incremental_on_dropped_edges"]
                or inc["recovered_fn"] != 0 or inc["added_edges"] != 0):
            ok_all = False
        out[ds] = ds_out

    out["ok_all"] = ok_all
    dst = WS / "gate4b0" / "results" / "fn_attribution.json"
    dst.parent.mkdir(exist_ok=True)
    with open(dst, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{'PASS' if ok_all else 'FAIL'} -> {dst}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
