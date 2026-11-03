"""Independent fbin-based distance cross-check and complete conversion validation."""
import argparse
import array
import hashlib
import json
import struct
import sys
from pathlib import Path
from evaluate import load_gt


def check(bvecs, fbin, gt_path, diagnostic_path):
    raw = Path(bvecs).read_bytes()
    with Path(fbin).open("rb") as f:
        n, d = struct.unpack("<II", f.read(8))
        flat = array.array("f")
        flat.frombytes(f.read())
    if sys.byteorder != "little":
        flat.byteswap()
    if (n, d) != (100000, 128) or len(flat) != n*d or len(raw) != n*(d+4):
        raise ValueError("expected complete BigANN100K 128d inputs")
    for i in range(n):
        start = i*(d+4)
        if struct.unpack_from("<I", raw, start)[0] != d:
            raise ValueError(f"bad bvecs header at {i}")
        if any(a != b for a, b in zip(flat[i*d:(i+1)*d], raw[start+4:start+4+d])):
            raise ValueError(f"conversion mismatch at {i}")
    gt = load_gt(gt_path, n)
    diag = load_gt(diagnostic_path, n)
    # Independent data representation and algebra: norms/dot product, not d2().
    ids = [0] + sorted(gt)[:3]
    rows = [tuple(map(int, flat[i*d:(i+1)*d])) for i in range(n)]
    norms = [sum(v*v for v in row) for row in rows]
    for e in ids:
        expected = {j for j in range(n) if j != e and
                    norms[e]+norms[j]-2*sum(a*b for a, b in zip(rows[e], rows[j])) < 272*272}
        if expected != (diag if e == 0 else gt)[e]:
            raise ValueError(f"independent complete neighborhood mismatch at endpoint {e}")
    return dict(n=n, d=d, conversion="all coordinates equal", independent_endpoints=ids,
                threshold=73984, sha256={str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                        for p in [bvecs, fbin]})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("bvecs"); p.add_argument("fbin"); p.add_argument("gt"); p.add_argument("diagnostic")
    a = p.parse_args()
    print(json.dumps(check(a.bvecs, a.fbin, a.gt, a.diagnostic), indent=2))
