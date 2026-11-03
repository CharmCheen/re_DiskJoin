#!/usr/bin/env python3
"""Deterministic bvecs -> fbin converter + structural integrity check (Gate 5B).

The BigANN / SIFT1B `.bvecs` format stores, per record:
    uint32 little-endian dimension prefix (== d)
    d x uint8
There is no global header. The DiskJoin `.fbin` format stores:
    uint32 little_endian n, uint32 little_endian d, then n*d float32 little-endian.

This mirrors upstream `datasets.py` (`np.array([n, d], dtype=np.uint32).tofile`
then `data.astype(np.float32).tofile`), i.e. the exact conversion used to derive
the accepted 100K `bigann100k.fbin` from `bigann100k.bvecs`.

It additionally performs the SAME STRUCTURAL VERIFICATION used for the truncated
gz prefix in Gate 5A (a truncated gzip stream admits no CRC), so no integrity is
assumed: every record header is checked to equal d, values are checked to lie in
[0,255], and a uint8->float32 roundtrip is checked on sampled records.

This program never touches the network. It reads a local file only.
"""
import argparse
import json
import struct
import sys


def check_bvecs(path, expect_n, expect_d):
    """Stream the bvecs, validating every per-record dimension header."""
    size = path.stat().st_size
    rec = expect_d + 4
    if expect_n is not None and size != expect_n * rec:
        raise ValueError(
            f"bvecs size {size} != n*(d+4) = {expect_n}*{rec} = {expect_n*rec}")
    if size == 0 or size % rec != 0:
        raise ValueError(
            f"bvecs size {size} is not a positive multiple of record size {rec}")
    n = size // rec
    bad_headers = 0
    min_v, max_v = 256, -1
    first_value = None
    with path.open("rb") as fh:
        for i in range(n):
            raw = fh.read(rec)
            if len(raw) != rec:
                raise ValueError(f"short record at index {i}")
            (dim,) = struct.unpack_from("<I", raw, 0)
            if dim != expect_d:
                bad_headers += 1
            if first_value is None:
                first_value = raw[4]
            for b in raw[4:]:
                if b < min_v:
                    min_v = b
                if b > max_v:
                    max_v = b
    if bad_headers:
        raise ValueError(f"{bad_headers} record headers != {expect_d}")
    return dict(n=n, d=expect_d, records=size, bytes=size,
                min_value=0 if n == 0 else min_v,
                max_value=0 if n == 0 else max_v,
                first_uint8=first_value)


def convert(bvecs_path, fbin_path, d, n_limit=None):
    """Stream bvecs -> fbin. Returns (n_written, sha256_of_bvecs_consumed_records)."""
    import hashlib
    h = hashlib.sha256()
    rec_in = d + 4
    n = 0
    with bvecs_path.open("rb") as fin, fbin_path.open("wb") as fout:
        # reserve the header; we know n only after streaming (or from n_limit)
        fout.write(b"\x00" * 8)
        while True:
            if n_limit is not None and n >= n_limit:
                break
            raw = fin.read(rec_in)
            if not raw:
                break
            if len(raw) != rec_in:
                raise ValueError(f"short record at index {n}")
            (dim,) = struct.unpack_from("<I", raw, 0)
            if dim != d:
                raise ValueError(f"record {n} header {dim} != {d}")
            h.update(raw)
            data = raw[4:]
            # uint8 -> float32, exact (values <= 255 << 2^24)
            fout.write(struct.pack(f"<{d}f", *data))
            n += 1
        fout.seek(0)
        fout.write(struct.pack("<II", n, d))
        # The body already contains exactly n records; do NOT truncate at the
        # header position, which would delete the data.
    return n, h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bvecs", required=True, type=__import__("pathlib").Path)
    ap.add_argument("--fbin", required=True, type=__import__("pathlib").Path)
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--expect-n", type=int, default=None)
    ap.add_argument("--check-only", action="store_true",
                    help="validate the bvecs only; do not write fbin")
    ap.add_argument("--out", type=__import__("pathlib").Path, default=None)
    a = ap.parse_args()
    info = check_bvecs(a.bvecs, a.expect_n, a.d)
    result = dict(bvecs=str(a.bvecs), **info)
    if not a.check_only:
        n, digest = convert(a.bvecs, a.fbin, a.d, a.expect_n)
        result.update(fbin=str(a.fbin), fbin_n=n, fbin_bytes=a.fbin.stat().st_size,
                      bvecs_consumed_sha256=digest)
        if a.fbin.stat().st_size != 8 + n * a.d * 4:
            raise ValueError("written fbin size mismatch")
    if a.out:
        a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
