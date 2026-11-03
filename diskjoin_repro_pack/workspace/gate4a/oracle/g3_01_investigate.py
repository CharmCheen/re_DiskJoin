#!/usr/bin/env python3
"""G3-01 supplemental investigation: 2-choice bucketization vs nearest-center.

Question (Gate 3 finding): all/most centroids are NOT in their own bucket.
Is this (a) a data-parsing error, (b) HNSW approximation returning non-nearest
centers, or (c) the documented add2choice 2-choice load balancing?

Method (independent of the C++ reader):
  1. read metadata (centroids, assignment) + fbin;
  2. exact float32-tuple match each centroid to its source data vector
     -> center_id[b]  (parsing check: must match exactly, uniquely);
  3. check center_id[b] in assignment[b]  (own-bucket membership);
  4. brute-force TRUE nearest/2nd-nearest centroid for each center vector
     and for a sample of data vectors;
  5. classify each vector's assigned bucket as {nearest, 2nd, other}.

If assignments are always within {nearest, 2nd} and own-bucket misses are
correlated with bucket occupancy, the phenomenon is consistent with 2-choice
load balancing (paper's add2choice), not a parsing error.
"""
import argparse
import array
import json
import random
import struct
import sys
from pathlib import Path


def read_meta(path):
    with open(path, "rb") as f:
        raw = f.read()
    n, d, cn, mp = struct.unpack_from("<QQQQ", raw, 0)
    off = 32
    bs = struct.unpack_from("<%dQ" % cn, raw, off); off += 8 * cn
    cent = array.array("f"); cent.frombytes(raw[off:off + cn * d * 4]); off += cn * d * 4
    rad = array.array("f"); rad.frombytes(raw[off:off + cn * 4]); off += cn * 4
    assignment = []
    for i in range(cn):
        a = array.array("Q"); a.frombytes(raw[off:off + bs[i] * 8]); off += bs[i] * 8
        assignment.append(a)
    return n, d, cn, bs, cent, assignment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--fbin", required=True)
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=99)
    ap.add_argument("--out")
    args = ap.parse_args()

    n, d, cn, bs, cent, assignment = read_meta(args.metadata)
    with open(args.fbin, "rb") as f:
        f.read(8)
        flat = array.array("f"); flat.frombytes(f.read(n * d * 4))

    vec = lambda i: flat[i * d:(i + 1) * d]
    cvec = lambda b: cent[b * d:(b + 1) * d]

    # 1. exact centroid -> source vector match
    by_data = {}
    for i in range(n):
        by_data.setdefault(tuple(vec(i)), []).append(i)
    matches, ambiguous, unmatched = [], 0, 0
    for b in range(cn):
        ids = by_data.get(tuple(cvec(b)))
        if not ids:
            unmatched += 1; matches.append(None)
        elif len(ids) > 1:
            ambiguous += 1; matches.append(ids)
        else:
            matches.append(ids[0])
    print("centroids: %d total, unmatched=%d, ambiguous=%d, unique=%d"
          % (cn, unmatched, ambiguous, sum(1 for m in matches if isinstance(m, int))))

    # distinct centroid check (nearest of center b must be b itself at dist 0)
    dup_centroid = sum(1 for b in range(cn)
                       if any(cvec(b) == cvec(b2) for b2 in range(b + 1, cn)))

    # 2. own-bucket membership of the center vector
    own = 0
    for b in range(cn):
        if isinstance(matches[b], int) and matches[b] in assignment[b]:
            own += 1

    # 3. assigned bucket of each data vector + true nearest/2nd centers
    rng = random.Random(args.seed)
    ids = sorted(rng.sample(range(n), min(args.sample, n))) + \
          sorted({m for m in matches if isinstance(m, int)})
    def top2(x):
        d1 = d2 = None; c1 = c2 = -1
        for b in range(cn):
            cv = cvec(b)
            s = 0.0
            for k in range(d):
                t = x[k] - cv[k]
                s += t * t
            if d1 is None or s < d1:
                d2, c2 = d1, c1; d1, c1 = s, b
            elif d2 is None or s < d2:
                d2, c2 = s, b
        return c1, c2, d1, d2
    id_bucket = {}
    for b in range(cn):
        for i in assignment[b]:
            id_bucket[i] = b
    cls = {"nearest": 0, "second": 0, "other": 0}
    center_cls = {"nearest": 0, "second": 0, "other": 0}
    ratio_ok = 0; ratio_cnt = 0
    for i in ids:
        c1, c2, d1, d2 = top2(vec(i))
        ab = id_bucket[i]
        k = "nearest" if ab == c1 else ("second" if ab == c2 else "other")
        cls[k] += 1
        if i in {m for m in matches if isinstance(m, int)}:
            center_cls[k] += 1
        if i in {m for m in matches if isinstance(m, int)} and d2 and d2 > 0:
            ratio_cnt += 1
            if d1 < 1.2 * d2:
                ratio_ok += 1
    report = {
        "n": n, "d": d, "cluster_num": cn,
        "centroid_unique_matches": sum(1 for m in matches if isinstance(m, int)),
        "centroid_unmatched": unmatched, "centroid_ambiguous": ambiguous,
        "duplicate_centroids": dup_centroid,
        "center_in_own_bucket": own, "center_not_in_own_bucket": cn - own,
        "sampled_vectors": len(ids),
        "assigned_is_nearest": cls["nearest"],
        "assigned_is_second": cls["second"],
        "assigned_is_other": cls["other"],
        "centers_assigned_nearest": center_cls["nearest"],
        "centers_assigned_second": center_cls["second"],
        "centers_assigned_other": center_cls["other"],
        "centers_with_d1_lt_1.2_d2": ratio_ok, "centers_with_d2": ratio_cnt,
    }
    print(json.dumps(report, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
