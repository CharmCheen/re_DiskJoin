#!/usr/bin/env python3
"""Compare DiskJoin pair output against the independent oracle GT (Gate 3B).

Reads two whitespace-separated files of "min max" pairs:
  --gt    ground-truth pairs from oracle_pairs.py
  --found pairs dumped by the instrumented DiskJoin (GATE3_PAIR_OUT)

Reports: GT count, found count, TP, FP, FN, recall, precision, duplicate
count, illegal count, and a few sample FP / FN pairs (with recomputed
squared-L2 distances for the inspected vectors when --fbin is given).
"""
import argparse
import array
import json


def read_pairs(path, n=None):
    pairs = []
    illegal = 0
    with open(path) as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                illegal += 1
                continue
            try:
                a = int(parts[0])
                b = int(parts[1])
            except ValueError:
                illegal += 1
                continue
            if a < 0 or b < 0 or a == b or a > b:
                illegal += 1
                continue
            if n is not None and (a >= n or b >= n):
                illegal += 1
                continue
            pairs.append((a, b))
    return pairs, illegal


def load_vectors(path, d):
    with open(path, "rb") as f:
        hdr = f.read(8)
        nn = int.from_bytes(hdr[0:4], "little")
        dd = int.from_bytes(hdr[4:8], "little")
        flat = array.array("f")
        flat.frombytes(f.read(nn * dd * 4))
    return nn, dd, flat


def sq_l2(flat, d, i, j):
    a = flat[i * d:(i + 1) * d]
    b = flat[j * d:(j + 1) * d]
    return sum((x - y) * (x - y) for x, y in zip(a, b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--found", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--radius", type=float, default=0.0625)
    ap.add_argument("--fbin")
    ap.add_argument("--sample", type=int, default=5)
    args = ap.parse_args()

    gt_list, gt_illegal = read_pairs(args.gt, args.n)
    found_list, found_illegal = read_pairs(args.found, args.n)

    gt = set(gt_list)
    gt_dups = len(gt_list) - len(gt)
    found = set(found_list)
    found_dups = len(found_list) - len(found)

    tp = len(gt & found)
    fp = found - gt
    fn = gt - found
    recall = tp / (tp + len(fn)) if (tp + len(fn)) else 1.0
    precision = tp / (tp + len(fp)) if (tp + len(fp)) else 1.0

    report = {
        "n": args.n,
        "radius": args.radius,
        "gt_pairs": len(gt),
        "gt_illegal_lines": gt_illegal,
        "gt_duplicates": gt_dups,
        "found_pairs": len(found),
        "found_illegal_lines": found_illegal,
        "found_duplicates": found_dups,
        "TP": tp, "FP": len(fp), "FN": len(fn),
        "recall": recall, "precision": precision,
    }
    print(json.dumps(report, indent=2))

    if args.fbin:
        nn, dd, flat = load_vectors(args.fbin, 0)
        if fp:
            print("sample FP (in output, not in GT):")
            for (a, b) in sorted(fp)[:args.sample]:
                print("  (%d,%d) sq_l2=%.8f >= radius=%.8f" % (a, b, sq_l2(flat, dd, a, b), args.radius))
        if fn:
            print("sample FN (in GT, not in output):")
            for (a, b) in sorted(fn)[:args.sample]:
                print("  (%d,%d) sq_l2=%.8f <  radius=%.8f" % (a, b, sq_l2(flat, dd, a, b), args.radius))


if __name__ == "__main__":
    main()
