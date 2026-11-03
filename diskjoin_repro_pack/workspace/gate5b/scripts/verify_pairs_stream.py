#!/usr/bin/env python3
"""Streaming pair-output verifier for DiskJoin (Gate 5B).

Purpose: verify a joiner's pair output WITHOUT holding all pairs in memory, and
compare two versions. Three independent capabilities:

  verify   Stream pairs.txt once and report: total count, illegal IDs, self
           joins, reversed pairs, out-of-range IDs, the predicted neighbour set
           for the small sampled-endpoint set only (tp/fp/predicted), and a
           streaming SHA-256 of the raw byte stream.

           Duplicate detection is EXPLICIT and never inferred from sums/xor:
             * the stream is checked for global non-decreasing order by (a,b);
             * if sorted, duplicates == adjacent equal pairs (exact, O(1) RAM);
             * otherwise, if --dup-mode external-sort, the file is externally
               sorted with a memory cap (-S) into a temp file and re-streamed,
               giving an EXACT global duplicate count with bounded RAM;
             * otherwise duplicates are reported UNVERIFIED (never "0").

  compare  Two versions. If the order is determined (--ordered) streams both in
           lockstep via SHA-256. Otherwise (or --unordered) externally sorts both
           with a RAM cap and compares the sorted streams -> bounded set compare.

  Counts, sums and xor are NEVER used to claim absence of duplicates.

Exit code: 0 if the requested checks pass, 1 if a violation is found or a
required exact check could not be performed (UNVERIFIED), 2 on usage error.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "oracle"))


def load_gt_endpoints(gt_paths, n):
    """Load only the sampled endpoints and their GT sets (small)."""
    gt = {}
    for path in gt_paths:
        if path is None:
            continue
        for line in Path(path).read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            e, k, *ids = map(int, line.split())
            if e in gt or not 0 <= e < n or k != len(ids) or e in ids:
                raise ValueError(f"invalid GT row at endpoint {e}")
            gt[e] = set(ids)
    return gt


def stream_pairs(pairs, n, endpoints, hasher=None, sorted_check=True):
    """Single pass. Returns counters; never stores non-endpoint pairs."""
    total = illegal = self_join = reversed_pair = out_of_range = bad_line = 0
    adjacent_duplicates = 0
    non_decreasing = True
    prev = None
    found = {e: set() for e in endpoints}
    current = hashlib.sha256() if hasher is None else hasher
    with open(pairs, "rb") as fh:
        for raw in fh:
            current.update(raw)
            text = raw.strip()
            if not text:
                continue
            parts = text.split()
            if len(parts) != 2:
                bad_line += 1
                continue
            try:
                a, b = int(parts[0]), int(parts[1])
            except ValueError:
                bad_line += 1
                continue
            total += 1
            if a == b:
                self_join += 1
            if a > b:
                reversed_pair += 1
            if not (0 <= a < n and 0 <= b < n):
                out_of_range += 1
            if not (0 <= a < b < n):
                illegal += 1
            pair = (a, b)
            if prev is not None and pair == prev:
                adjacent_duplicates += 1
            if prev is not None and pair < prev and sorted_check:
                non_decreasing = False
            prev = pair
            if a in found:
                found[a].add(b)
            if b in found:
                found[b].add(a)
    return dict(total=total, illegal=illegal, self_joins=self_join,
                reversed=reversed_pair, out_of_range=out_of_range,
                bad_lines=bad_line, adjacent_duplicates=adjacent_duplicates,
                sorted_non_decreasing=non_decreasing, sha256=current.hexdigest(),
                found=found)


def external_sort(src, tmp_dir, mem_mb):
    """Exact external sort of canonical (a,b) lines with a RAM cap. Returns path."""
    out = Path(tempfile.mkstemp(dir=tmp_dir, suffix=".sorted")[1])
    env = dict(os.environ)
    with open(src, "rb") as fin, open(out, "wb") as fout:
        proc = subprocess.run(
            ["sort", "-n", "-k1,1", "-k2,2", f"-S{mem_mb}M", "-T", str(tmp_dir)],
            stdin=fin, stdout=fout, env=env)
    if proc.returncode != 0:
        raise RuntimeError("external sort failed")
    return out


def exact_duplicates_via_sort(pairs, n, tmp_dir, mem_mb):
    """Exact global duplicate count with bounded RAM using external sort."""
    sorted_path = external_sort(pairs, tmp_dir, mem_mb)
    dups = 0
    total = 0
    prev = None
    with open(sorted_path) as fh:
        for line in fh:
            a, b = map(int, line.split())
            total += 1
            cur = (a, b)
            if cur == prev:
                dups += 1
            prev = cur
    sorted_path.unlink()
    return dups, total


def endpoint_rows(found, gt):
    rows = {}
    for e in sorted(gt):
        pred = found.get(e, set())
        rows[e] = dict(endpoint=e, gt=len(gt[e]), tp=len(pred & gt[e]),
                       fp=len(pred - gt[e]), predicted=len(pred))
    return rows


def cmd_verify(a):
    endpoints = set(load_gt_endpoints([a.gt, a.diagnostic_gt], a.n))
    res = stream_pairs(a.pairs, a.n, endpoints)
    found = res.pop("found")
    gt = load_gt_endpoints([a.gt, a.diagnostic_gt], a.n)
    rows = endpoint_rows(found, gt)

    # Duplicate resolution, explicit and honest.
    if res["sorted_non_decreasing"]:
        dup_count, dup_verified, dup_method = res["adjacent_duplicates"], True, "adjacent-equal (stream verified non-decreasing)"
    elif a.dup_mode == "external-sort":
        dup_count, _ = exact_duplicates_via_sort(a.pairs, a.n, a.tmp, a.sort_mem_mb)
        dup_verified, dup_method = True, f"external sort -S{a.sort_mem_mb}M then adjacent-equal"
    else:
        dup_count, dup_verified, dup_method = None, False, "UNVERIFIED (stream not non-decreasing; no exact dup scan requested)"

    out = dict(pairs=str(a.pairs), n=a.n, **res,
               duplicates=dup_count, duplicates_verified=dup_verified,
               duplicate_method=dup_method,
               sampled_endpoints=rows)
    summary = dict(total=out["total"], illegal=out["illegal"], self_joins=out["self_joins"],
                   out_of_range=out["out_of_range"], duplicates=out["duplicates"],
                   duplicates_verified=out["duplicates_verified"],
                   sha256=out["sha256"], endpoints=len(rows),
                   sampled_fp=sum(r["fp"] for r in rows.values()))
    out["summary"] = summary
    if a.out:
        a.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    ok = (res["illegal"] == 0 and res["bad_lines"] == 0 and dup_verified and dup_count == 0)
    return 0 if ok else 1


def cmd_compare(a):
    if a.ordered:
        h1, h2 = hashlib.sha256(), hashlib.sha256()
        n1 = n2 = 0
        equal = True
        with open(a.left, "rb") as f1, open(a.right, "rb") as f2:
            while True:
                l1 = f1.readline()
                l2 = f2.readline()
                if not l1 and not l2:
                    break
                h1.update(l1); h2.update(l2)
                n1 += bool(l1); n2 += bool(l2)
                if l1 != l2:
                    equal = False
        result = dict(mode="ordered-stream", equal=equal and n1 == n2,
                      left_sha256=h1.hexdigest(), right_sha256=h2.hexdigest(),
                      left_lines=n1, right_lines=n2)
    else:
        s1 = external_sort(a.left, a.tmp, a.sort_mem_mb)
        s2 = external_sort(a.right, a.tmp, a.sort_mem_mb)
        h1, h2 = hashlib.sha256(), hashlib.sha256()
        n1 = n2 = 0
        equal = True
        with open(s1, "rb") as f1, open(s2, "rb") as f2:
            while True:
                l1 = f1.readline(); l2 = f2.readline()
                if not l1 and not l2:
                    break
                h1.update(l1); h2.update(l2)
                n1 += bool(l1); n2 += bool(l2)
                if l1 != l2:
                    equal = False
        s1.unlink(); s2.unlink()
        result = dict(mode="external-sort-set", equal=equal and n1 == n2,
                      sorted_sha256_left=h1.hexdigest(), sorted_sha256_right=h2.hexdigest(),
                      left_lines=n1, right_lines=n2,
                      note="multiset equality via exact external sort; bounded RAM")
    if a.out:
        a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["equal"] else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify")
    v.add_argument("--pairs", type=Path, required=True)
    v.add_argument("--n", type=int, required=True)
    v.add_argument("--gt", type=Path, default=None)
    v.add_argument("--diagnostic-gt", type=Path, default=None)
    v.add_argument("--dup-mode", choices=["auto", "external-sort"], default="auto")
    v.add_argument("--sort-mem-mb", type=int, default=256)
    v.add_argument("--tmp", type=Path, default=Path("/tmp/opencode"))
    v.add_argument("--out", type=Path, default=None)
    v.set_defaults(func=cmd_verify)

    c = sub.add_parser("compare")
    c.add_argument("--left", type=Path, required=True)
    c.add_argument("--right", type=Path, required=True)
    c.add_argument("--ordered", action="store_true",
                   help="order is determined: lockstep streaming SHA-256 compare")
    c.add_argument("--sort-mem-mb", type=int, default=256)
    c.add_argument("--tmp", type=Path, default=Path("/tmp/opencode"))
    c.add_argument("--out", type=Path, default=None)
    c.set_defaults(func=cmd_compare)

    a = p.parse_args()
    a.tmp.mkdir(parents=True, exist_ok=True)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
