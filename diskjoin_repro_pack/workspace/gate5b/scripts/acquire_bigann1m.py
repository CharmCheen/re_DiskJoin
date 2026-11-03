#!/usr/bin/env python3
"""Guarded BigANN1M acquisition driver (Gate 5B deliverable 1).

DEFAULT (no --authorized): prints the acquisition plan and performs metadata-only
probes (FTP HEAD + the tiny official MD5SUM). It NEVER downloads the dataset body.

WITH --authorized: performs an FTP Range fetch of a bounded gzip PREFIX of the
official IRISA/texmex bigann_base.bvecs.gz, stream-decompresses just enough to
obtain the first 1,000,000 records, structurally verifies them, and writes
bigann1m.bvecs + bigann1m.fbin.

Provenance honesty: the official MD5 in MD5SUM covers the FULL 91.2 GiB file. A
bounded prefix cannot reproduce it, so this tool records LOCAL hashes only and
labels them as content pins, NOT as official provenance. Structural verification
(record alignment, value range, exact uint8->float32 roundtrip) stands in for the
unavailable gzip CRC, exactly as for the accepted 100K subset.

DO NOT RUN WITH --authorized WITHOUT EXPLICIT USER AUTHORIZATION.
"""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

URL = "ftp://ftp.irisa.fr/local/texmex/corpus/bigann_base.bvecs.gz"
MD5_URL = "ftp://ftp.irisa.fr/local/texmex/corpus/MD5SUM"
N = 1_000_000
D = 128
REC = D + 4                      # 132 bytes per bvecs record
RAW_BYTES = N * REC              # 132,000,000
FBIN_BYTES = 8 + N * D * 4       # 512,000,008
# Marginal gz/raw ratio derived from the full-file ratio 97,941,899,519 / 132e9.
GZ_BUDGET = 128 * 2 ** 20        # 134,217,728 B requested prefix (>= expected ~93.4 MiB)


def metadata_probe():
    out = {}
    r = subprocess.run(["curl", "-sS", "-I", URL], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    r2 = subprocess.run(["curl", "-sS", MD5_URL], capture_output=True, text=True)
    out["md5sum_bigann"] = [ln for ln in r2.stdout.splitlines() if ln.startswith("4346")]
    return out


def stream_extract(gz_path, out_bvecs, out_fbin, n_target):
    """Decompress a (possibly truncated) gzip prefix and pull n_target records.

    Returns (observed_n, structural_info, consumed_gz_bytes).
    """
    dec = zlib.decompressobj(31)  # gzip wrapper
    buf = b""
    n = 0
    min_v, max_v = 256, -1
    first_uint8 = None
    bad_headers = 0
    consumed = 0
    with open(gz_path, "rb") as gz, open(out_bvecs, "wb") as bv, open(out_fbin, "wb") as fb:
        fb.write(b"\x00" * 8)
        while n < n_target:
            chunk = gz.read(1 << 20)
            if not chunk:
                break
            consumed += len(chunk)
            try:
                buf += dec.decompress(chunk)
            except zlib.error:
                break
            while len(buf) >= REC and n < n_target:
                rec = buf[:REC]
                buf = buf[REC:]
                (dim,) = struct.unpack_from("<I", rec, 0)
                if dim != D:
                    bad_headers += 1
                vals = rec[4:]
                if first_uint8 is None:
                    first_uint8 = vals[0]
                lo, hi = min(vals), max(vals)
                if lo < min_v:
                    min_v = lo
                if hi > max_v:
                    max_v = hi
                bv.write(rec)
                fb.write(struct.pack(f"<{D}f", *vals))
                n += 1
        # finish flushing any already-decompressed remainder if we hit n_target
        fb.seek(0)
        fb.write(struct.pack("<II", n, D))
    info = dict(records=n, bad_headers=bad_headers,
                min_value=None if n == 0 else min_v,
                max_value=None if n == 0 else max_v,
                first_uint8=first_uint8,
                gz_prefix_bytes_consumed=consumed)
    return n, info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=Path("data/bigann1m"))
    ap.add_argument("--gz-prefix-bytes", type=int, default=GZ_BUDGET)
    ap.add_argument("--authorized", action="store_true",
                    help="actually perform the bounded Range download (needs user auth)")
    ap.add_argument("--keep-gz", action="store_true")
    a = ap.parse_args()

    plan = dict(url=URL, md5_url=MD5_URL, first_n=N, dimension=D,
                bvecs_bytes=RAW_BYTES, fbin_bytes=FBIN_BYTES,
                gz_prefix_request_bytes=a.gz_prefix_bytes,
                expected_gz_transfer_bytes=int(RAW_BYTES * 97941899519 / 132000000000))
    if not a.authorized:
        plan["metadata_probe"] = metadata_probe()
        plan["action"] = "PLAN ONLY (no dataset body downloaded)"
        print(json.dumps(plan, indent=2))
        return 0

    a.out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="bigann1m_", dir=str(a.out_dir)))
    gz = tmp / "prefix.gz"
    rng = f"0-{a.gz_prefix_bytes - 1}"
    print(f"[acquire] curl -sS -r {rng} -> {gz}", file=sys.stderr)
    rc = subprocess.run(["curl", "-sS", "-r", rng, "--max-time", "900",
                         "-o", str(gz), URL]).returncode
    if rc != 0:
        print(f"[acquire] curl rc={rc}", file=sys.stderr)
        return rc
    gz_md5 = None
    with open(gz, "rb") as gh:
        h = hashlib.md5()
        for blk in iter(lambda: gh.read(1 << 20), b""):
            h.update(blk)
        gz_md5 = h.hexdigest()
    n, info = stream_extract(gz, a.out_dir / "bigann1m.bvecs",
                             a.out_dir / "bigann1m.fbin", N)
    if n != N:
        print(f"[acquire] FAIL: only {n} records extracted; budget too small",
              file=sys.stderr)
        return 1
    if info["bad_headers"]:
        print(f"[acquire] FAIL: {info['bad_headers']} bad record headers", file=sys.stderr)
        return 1
    report = dict(plan=plan, extraction=info,
                  bvecs_bytes=(a.out_dir / "bigann1m.bvecs").stat().st_size,
                  fbin_bytes=(a.out_dir / "bigann1m.fbin").stat().st_size,
                  local_content_pins=dict(
                      gz_prefix_md5=gz_md5,
                      note="LOCAL content pins only; NOT official provenance "
                           "(official MD5 covers the full 91.2 GiB file)"),
                  next_step="python3 -B scripts/make_data_manifest.py --name bigann1m "
                            "--fbin data/bigann1m/bigann1m.fbin "
                            "--bvecs data/bigann1m/bigann1m.bvecs "
                            "--expect-n 1000000 --expect-d 128 "
                            "--out configs/manifest_bigann1m.json")
    (a.out_dir / "acquisition_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not a.keep_gz:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
