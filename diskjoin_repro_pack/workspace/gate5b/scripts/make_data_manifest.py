#!/usr/bin/env python3
"""Generate a *validated* data manifest from a real fbin (and optional bvecs).

The manifest is the single source of truth for n, dimension, file sizes and
SHA-256 that the Oracle, the run validator and the endpoint sampler consume,
replacing the 100K-only literals (100000/128, bucket_sum, sizes, hashes).

Validation performed (no checks are disabled, they are moved to the manifest):
  * fbin header (uint32 LE n, uint32 LE d);
  * fbin byte length == 8 + n*d*4;
  * optional bvecs byte length == n*(d+4);
  * optional bvecs per-record dimension prefix == d for EVERY record;
  * optional --expect-n / --expect-d equality.

Exit non-zero on any mismatch. Nothing here downloads or fabricates data.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(name, fbin, bvecs, provenance, expect_n, expect_d):
    fbin = Path(fbin)
    size = fbin.stat().st_size
    with fbin.open("rb") as f:
        head = f.read(8)
    if len(head) != 8:
        raise SystemExit(f"fbin too small for header: {fbin}")
    n, d = struct.unpack("<II", head)
    if n == 0 or d == 0:
        raise SystemExit(f"degenerate fbin header n={n} d={d}")
    expected = 8 + n * d * 4
    if size != expected:
        raise SystemExit(f"fbin size {size} != 8+n*d*4={expected} (n={n},d={d})")
    if expect_n is not None and n != expect_n:
        raise SystemExit(f"fbin n={n} != expected {expect_n}")
    if expect_d is not None and d != expect_d:
        raise SystemExit(f"fbin d={d} != expected {expect_d}")

    man = {
        "name": name,
        "n": n,
        "dimension": d,
        "fbin": {"path": str(fbin.resolve()), "bytes": size,
                 "header_n": n, "header_d": d, "sha256": sha256_file(fbin)},
        "record_layout": {
            "fbin": "uint32 n, uint32 d, then n*d float32 (little-endian)",
            "bvecs": "per record: uint32 dimension prefix, then dimension uint8",
        },
        "provenance": provenance,
    }

    if bvecs is not None:
        bvecs = Path(bvecs)
        bsize = bvecs.stat().st_size
        if bsize != n * (d + 4):
            raise SystemExit(f"bvecs size {bsize} != n*(d+4)={n * (d + 4)}")
        chk = 0
        with bvecs.open("rb") as f:
            for i in range(n):
                hdr = f.read(4)
                if len(hdr) != 4 or struct.unpack("<I", hdr)[0] != d:
                    raise SystemExit(f"bad bvecs dimension prefix at record {i}")
                f.seek(d, 1)
                chk += 1
        man["bvecs"] = {"path": str(bvecs.resolve()), "bytes": bsize,
                        "header_d": d, "records_checked": chk,
                        "sha256": sha256_file(bvecs)}
    return man


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--fbin", required=True)
    p.add_argument("--bvecs", default=None)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--provenance", default="")
    p.add_argument("--expect-n", type=int, default=None)
    p.add_argument("--expect-d", type=int, default=None)
    a = p.parse_args()
    man = build_manifest(a.name, a.fbin, a.bvecs, a.provenance, a.expect_n, a.expect_d)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(man, indent=2) + "\n")
    print(f"manifest OK: {a.out} n={man['n']} d={man['dimension']} "
          f"fbin_bytes={man['fbin']['bytes']}")


if __name__ == "__main__":
    sys.exit(main())
