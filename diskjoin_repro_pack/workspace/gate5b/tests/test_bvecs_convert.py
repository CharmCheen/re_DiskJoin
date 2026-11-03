"""Runnable (no-network) tests for the bvecs->fbin converter.

Synthetic data only: proves the converter is bit-exact and that its structural
checks reject malformed input. This is the deterministic stand-in for the
conversion that will run on the real BigANN1M bvecs once data is authorized.
"""
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bvecs_to_fbin.py"
sys.path.insert(0, str(ROOT / "scripts"))
import bvecs_to_fbin as conv  # noqa: E402


def make_bvecs(path, rows):
    with open(path, "wb") as f:
        for r in rows:
            f.write(struct.pack("<I", len(r)))
            f.write(bytes(r))


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_exact(self):
        d = 4
        rows = [[0, 1, 2, 255], [7, 7, 7, 7], [128, 0, 64, 32]]
        b = self.dir / "x.bvecs"
        make_bvecs(b, rows)
        f = self.dir / "x.fbin"
        n, digest = conv.convert(b, f, d, None)
        self.assertEqual(n, 3)
        raw = f.read_bytes()
        hn, hd = struct.unpack_from("<II", raw, 0)
        self.assertEqual((hn, hd), (3, 4))
        vals = struct.unpack_from("<12f", raw, 8)
        flat = [x for r in rows for x in r]
        self.assertEqual(list(vals), [float(x) for x in flat])
        self.assertEqual(f.stat().st_size, 8 + 3 * 4 * 4)

    def test_check_rejects_bad_header(self):
        b = self.dir / "bad.bvecs"
        with open(b, "wb") as f:
            f.write(struct.pack("<I", 128))  # declares d=128 but only 2 bytes follow
            f.write(b"\x01\x02")
        with self.assertRaises(Exception):
            conv.check_bvecs(b, None, 4)

    def test_check_rejects_wrong_expected_n(self):
        d = 4
        b = self.dir / "n.bvecs"
        make_bvecs(b, [[1, 2, 3, 4]])
        with self.assertRaises(Exception):
            conv.check_bvecs(b, expect_n=2, expect_d=d)

    def test_cli_writes_json(self):
        d = 4
        b = self.dir / "c.bvecs"
        make_bvecs(b, [[9, 8, 7, 6], [5, 4, 3, 2]])
        f = self.dir / "c.fbin"
        out = self.dir / "c.json"
        r = subprocess.run([sys.executable, "-B", str(SCRIPT), "--bvecs", str(b),
                            "--fbin", str(f), "--d", "4", "--expect-n", "2",
                            "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(out.read_text())
        self.assertEqual(j["n"], 2)
        self.assertEqual(j["fbin_bytes"], 8 + 2 * 4 * 4)
        self.assertEqual(j["min_value"], 2)
        self.assertEqual(j["max_value"], 9)


if __name__ == "__main__":
    unittest.main()
