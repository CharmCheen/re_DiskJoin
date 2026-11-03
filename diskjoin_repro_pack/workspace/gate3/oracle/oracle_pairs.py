#!/usr/bin/env python3
"""Independent brute-force oracle for DiskJoin similarity self-join (Gate 3B).

Definition (paper Definition 1, L2):
    GT = { (i, j) | 0 <= j < i < n,  ||x_i - x_j||_2 < epsilon }
which the reference code evaluates as squared L2:
    dist_l2(x_i, x_j) < epsilon^2 == config.radius        (strict <)
so this oracle uses   squared_L2 < radius   with the config `radius` value
(= epsilon^2 for the toy; 0.0625).

This module is written in pure Python stdlib and is independent of the
DiskJoin C++ join implementation. It provides:

  * `gt_naive`    : exhaustive O(n^2) enumeration (ground truth, slow).
  * `gt_windowed` : exact enumeration pruned by the necessary condition
                    |x_i[0] - x_j[0]| < sqrt(radius). This does NOT change the
                    result set; it is cross-validated against `gt_naive`.
  * `selftest`    : hand-built cases (identical, boundary, far, duplicates).

No NumPy is used because the environment has no NumPy and no package
installation is authorised. The windowed path is O(n * neighbours) and is
validated exactly against the naive path on small inputs.
"""
import argparse
import array
import json
import math
import sys


def read_fbin(path):
    with open(path, "rb") as f:
        hdr = f.read(8)
        n = int.from_bytes(hdr[0:4], "little")
        d = int.from_bytes(hdr[4:8], "little")
        flat = array.array("f")
        flat.frombytes(f.read(n * d * 4))
    # snapshot to locals for speed
    return n, d, flat


def sq_l2(a, b):
    s = 0.0
    for x, y in zip(a, b):
        dx = x - y
        s += dx * dx
    return s


def gt_naive(n, d, flat, radius):
    """Exhaustive O(n^2) ground truth. Returns set of (i, j), i < j."""
    out = set()
    for i in range(n):
        vi = flat[i * d:(i + 1) * d]
        for j in range(i):
            vj = flat[j * d:(j + 1) * d]
            if sq_l2(vi, vj) < radius:
                out.add((j, i))
    return out


def gt_windowed(n, d, flat, radius, progress=False):
    """Exact, pruned by necessary condition on coordinate 0.

    If squared L2 < radius then |x_i[0]-x_j[0]| < sqrt(radius). Sorting by
    coordinate 0 and only scanning the forward window therefore yields exactly
    the same set as the naive scan. Validated against gt_naive in selftest.
    """
    r = math.sqrt(radius)
    idx = sorted(range(n), key=lambda i: flat[i * d])
    out = set()
    m = len(idx)
    for a in range(m):
        i = idx[a]
        vi = flat[i * d:(i + 1) * d]
        x0i = vi[0]
        for b in range(a + 1, m):
            j = idx[b]
            x0j = flat[j * d]
            if x0j - x0i >= r:
                break
            vj = flat[j * d:(j + 1) * d]
            if sq_l2(vi, vj) < radius:
                out.add((i, j) if i < j else (j, i))
        if progress and (a & 1023) == 0:
            sys.stderr.write("\r[windowed] %d/%d" % (a, m))
            sys.stderr.flush()
    if progress:
        sys.stderr.write("\n")
    return out


def id_neighbourhood(n, d, flat, radius, target):
    """Exact set of j != target with squared_L2(x_target, x_j) < radius."""
    vt = flat[target * d:(target + 1) * d]
    out = []
    for j in range(n):
        if j == target:
            continue
        if sq_l2(vt, flat[j * d:(j + 1) * d]) < radius:
            out.append(j)
    return out


def selftest():
    import random
    ok = True

    # 1. Hand cases with manually enumerated answers, d=4 (radius = squared L2)
    def mk(rows):
        f = array.array("f")
        for r_ in rows:
            f.extend(r_)
        return len(rows), 4, f

    # identical vectors -> pair counted once; far vector -> excluded
    n, d, f = mk([[0, 0, 0, 0], [0, 0, 0, 0], [9, 9, 9, 9]])
    gt = gt_naive(n, d, f, 0.25)
    exp = {(0, 1)}
    print("  case identical/far:", gt, "expected", exp, "OK" if gt == exp else "FAIL")
    ok &= (gt == exp)

    # exactly-at-threshold: dist^2 == radius must be EXCLUDED (strict <)
    n, d, f = mk([[0, 0, 0, 0], [0.5, 0, 0, 0]])  # dist^2 = 0.25 == radius
    gt = gt_naive(n, d, f, 0.25)
    exp = set()
    print("  case ==threshold:", gt, "expected", exp, "OK" if gt == exp else "FAIL")
    ok &= (gt == exp)

    # just-below-threshold included
    n, d, f = mk([[0, 0, 0, 0], [0.499, 0, 0, 0]])
    gt = gt_naive(n, d, f, 0.25)
    exp = {(0, 1)}
    print("  case <threshold:", gt, "expected", exp, "OK" if gt == exp else "FAIL")
    ok &= (gt == exp)

    # duplicates: 3 identical -> C(3,2)=3 unique unordered pairs
    n, d, f = mk([[1, 1, 1, 1]] * 3)
    gt = gt_naive(n, d, f, 0.25)
    exp = {(0, 1), (0, 2), (1, 2)}
    print("  case duplicates:", gt, "expected", exp, "OK" if gt == exp else "FAIL")
    ok &= (gt == exp)

    # 2. Cross-validate naive vs windowed on random data
    rng = random.Random(12345)
    for trial in range(4):
        nn = 200
        dd = 4
        pts = array.array("f")
        for _ in range(nn):
            for _k in range(dd):
                pts.append(rng.uniform(-1.0, 1.0))
        rad = 0.3
        a = gt_naive(nn, dd, pts, rad)
        b = gt_windowed(nn, dd, pts, rad)
        # id 0 neighbourhood must equal all pairs involving 0
        c = {(0, j) for j in id_neighbourhood(nn, dd, pts, rad, 0)}
        a0 = {p for p in a if p[0] == 0}
        print("  cross-validate trial %d: naive=%d windowed=%d match=%s id0=%d id0pair=%d"
              % (trial, len(a), len(b), a == b and a0 == c, len(c), len(a0)))
        ok &= (a == b and a0 == c)

    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fbin")
    ap.add_argument("--radius", type=float)
    ap.add_argument("--method", choices=["naive", "windowed"], default="windowed")
    ap.add_argument("--out")
    ap.add_argument("--max-n", type=int, default=0)
    ap.add_argument("--id-neighbourhood", type=int, default=-1)
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    n, d, flat = read_fbin(args.fbin)
    if args.max_n and args.max_n < n:
        n = args.max_n
    if args.id_neighbourhood >= 0:
        nb = id_neighbourhood(n, d, flat, args.radius, args.id_neighbourhood)
        print(json.dumps({"id": args.id_neighbourhood, "count": len(nb),
                          "neighbours": nb}))
        return
    if args.method == "naive":
        gt = gt_naive(n, d, flat, args.radius)
    else:
        gt = gt_windowed(n, d, flat, args.radius, progress=args.progress)
    print(json.dumps({"n": n, "d": d, "radius": args.radius,
                      "method": args.method, "gt_pairs": len(gt)}))
    if args.out:
        with open(args.out, "w") as f:
            for (i, j) in sorted(gt):
                f.write("%d %d\n" % (i, j))


if __name__ == "__main__":
    main()
