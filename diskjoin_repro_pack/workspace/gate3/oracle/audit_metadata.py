#!/usr/bin/env python3
"""Independent metadata / bucket-file / fbin correspondence audit (Gate 3A-B).

Parses the DiskJoin metadata.bin written by ClusterWriter::writeMetadata and the
bucket file written by ClusterWriter::writeClusters, and cross-checks them
against the source .fbin data. Independent of the C++ reader path.

Checks
  1. header n/d/cluster_num/max_points sanity.
  2. sum(bucket_sizes) == n.
  3. assignment is a permutation of 0..n-1 (no dup, no missing, ids in range).
  4. bucket file layout: bucket b starts at cumu_size*d*4 and contains exactly
     bucket_sizes[b] contiguous vectors; each equals fbin[assignment[b][l]]
     bit-for-bit.
  5. radii[b] == sqrt(max_{x in bucket b} squared_L2(x, centroid[b])).
  6. every centroid equals some data vector and lies in its own bucket.
"""
import argparse
import array
import json
import math
import struct
import sys


def read_meta(path):
    with open(path, "rb") as f:
        raw = f.read()
    off = 0
    sz = struct.Struct("<Q")
    n, d, cn, mp = struct.unpack_from("<QQQQ", raw, off); off += 32
    bs_struct = struct.Struct("<%dQ" % cn)
    bucket_sizes = list(bs_struct.unpack_from(raw, off)); off += 8 * cn
    cent = array.array("f"); cent.frombytes(raw[off:off + cn * d * 4]); off += cn * d * 4
    radii = array.array("f"); radii.frombytes(raw[off:off + cn * 4]); off += cn * 4
    assignment = []
    for i in range(cn):
        a = array.array("Q"); a.frombytes(raw[off:off + bucket_sizes[i] * 8]); off += bucket_sizes[i] * 8
        assignment.append(a)
    assert off == len(raw), (off, len(raw))
    return dict(n=n, d=d, cluster_num=cn, max_points=mp, bucket_sizes=bucket_sizes,
                centroids=cent, radii=radii, assignment=assignment)


def load_fbin(path):
    with open(path, "rb") as f:
        n, d = struct.unpack("<II", f.read(8))
        flat = array.array("f"); flat.frombytes(f.read(n * d * 4))
    return n, d, flat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--clusters", required=True)
    ap.add_argument("--fbin", required=True)
    args = ap.parse_args()

    m = read_meta(args.metadata)
    n, d, flat = load_fbin(args.fbin)
    rep = {"meta_n": m["n"], "meta_d": m["d"], "cluster_num": m["cluster_num"],
           "max_points": m["max_points"]}
    assert n == m["n"] and d == m["d"]
    rep["bucket_sizes_sum"] = sum(m["bucket_sizes"])
    rep["sum_equals_n"] = (rep["bucket_sizes_sum"] == n)
    rep["max_bucket_size_matches"] = (max(m["bucket_sizes"]) == m["max_points"])

    # 3. assignment permutation
    seen = bytearray(n)
    dup = 0; oob = 0; total = 0
    for b in range(m["cluster_num"]):
        a = m["assignment"][b]
        assert len(a) == m["bucket_sizes"][b]
        for idv in a:
            total += 1
            if idv >= n: oob += 1; continue
            if seen[idv]: dup += 1
            seen[idv] = 1
    missing = n - sum(seen)
    rep.update(assignment_total=total, assignment_dup=dup, assignment_oob=oob,
               assignment_missing=missing, assignment_is_permutation=(dup == 0 and oob == 0 and missing == 0))

    # 4. bucket file layout + bit-exact vector correspondence
    with open(args.clusters, "rb") as f:
        cdata = f.read()
    cumu = 0; mism = 0; checked = 0; first_bad = None
    for b in range(m["cluster_num"]):
        base = cumu * d * 4
        for l, idv in enumerate(m["assignment"][b]):
            o = base + l * d * 4
            got = struct.unpack_from("<%df" % d, cdata, o)
            exp = tuple(flat[idv * d:(idv + 1) * d])
            checked += 1
            if got != exp:
                mism += 1
                if first_bad is None:
                    first_bad = (b, l, idv)
        cumu += m["bucket_sizes"][b]
    rep.update(vectors_checked=checked, vector_mismatch=mism,
               cluster_file_bytes=len(cdata), expected_bytes=n * d * 4,
               first_mismatch=first_bad)

    # 5. radii
    rad_bad = 0; rad_first = None
    for b in range(m["cluster_num"]):
        cen = m["centroids"][b * d:(b + 1) * d]
        mx = 0.0
        for idv in m["assignment"][b]:
            v = flat[idv * d:(idv + 1) * d]
            s = 0.0
            for x, y in zip(v, cen):
                dx = x - y; s += dx * dx
            if s > mx: mx = s
        if abs(math.sqrt(mx) - m["radii"][b]) > 1e-5:
            rad_bad += 1
            if rad_first is None: rad_first = (b, math.sqrt(mx), m["radii"][b])
    rep.update(radius_mismatch=rad_bad, first_radius_mismatch=rad_first)

    # 6. centroids are data vectors and present in their own bucket
    vecset = {}
    for i in range(n):
        vecset.setdefault(tuple(flat[i * d:(i + 1) * d]), []).append(i)
    cen_not_data = 0; cen_not_self = 0; cen_examples = []
    for b in range(m["cluster_num"]):
        cen = tuple(m["centroids"][b * d:(b + 1) * d])
        ids = vecset.get(cen)
        if not ids:
            cen_not_data += 1
            if len(cen_examples) < 3: cen_examples.append(("not_a_vector", b))
        elif b not in ids:
            cen_not_self += 1
            if len(cen_examples) < 3: cen_examples.append(("not_in_own_bucket", b, list(ids)[:3]))
    rep.update(centroid_not_a_data_vector=cen_not_data, centroid_not_in_own_bucket=cen_not_self,
               centroid_examples=cen_examples)

    print(json.dumps(rep, indent=2))
    ok = (rep["sum_equals_n"] and rep["assignment_is_permutation"] and mism == 0
          and rad_bad == 0 and cen_not_data == 0)
    print("METADATA_AUDIT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
