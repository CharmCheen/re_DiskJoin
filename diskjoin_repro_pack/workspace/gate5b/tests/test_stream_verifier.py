"""Deterministic counterexample tests for the streaming pair verifier.

Each test constructs an adversarial pair file and asserts the verifier detects
the exact defect, or that an unordered/undetermined case is reported UNVERIFIED
(never falsely "no duplicates").
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_pairs_stream.py"
sys.path.insert(0, str(ROOT / "oracle"))
from evaluate import endpoint_counts  # noqa: E402

N = 10


def run(args):
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args],
                          capture_output=True, text=True)


class StreamVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def pairs(self, text, name="pairs.txt"):
        p = self.dir / name
        p.write_text(text)
        return p

    def verify(self, p, gt=None, diag=None, dup_mode="external-sort"):
        args = ["verify", "--pairs", str(p), "--n", str(N),
                "--dup-mode", dup_mode, "--tmp", str(self.dir)]
        if gt:
            args += ["--gt", str(gt)]
        if diag:
            args += ["--diagnostic-gt", str(diag)]
        out = self.dir / "out.json"
        args += ["--out", str(out)]
        r = run(args)
        return r, (json.loads(out.read_text()) if out.exists() else None)

    def test_clean_sorted_counts_and_digest(self):
        p = self.pairs("0 1\n0 2\n1 2\n")
        r, out = self.verify(p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["illegal"], 0)
        self.assertTrue(out["duplicates_verified"])
        self.assertEqual(out["duplicates"], 0)
        self.assertEqual(out["sha256"], __import__("hashlib").sha256(b"0 1\n0 2\n1 2\n").hexdigest())

    def test_duplicate_unsorted_exact_via_external_sort(self):
        p = self.pairs("3 4\n0 1\n3 4\n0 1\n3 4\n")
        r, out = self.verify(p, dup_mode="external-sort")
        self.assertEqual(out["duplicates_verified"], True)
        self.assertEqual(out["duplicates"], 3)  # (0,1) x1 extra, (3,4) x2 extra
        self.assertNotEqual(r.returncode, 0)

    def test_duplicate_unsorted_marked_unverified_without_exact_scan(self):
        p = self.pairs("3 4\n0 1\n3 4\n")
        r, out = self.verify(p, dup_mode="auto")
        self.assertFalse(out["duplicates_verified"])
        self.assertIsNone(out["duplicates"])
        self.assertNotEqual(r.returncode, 0)  # honest: cannot certify

    def test_self_join_detected(self):
        p = self.pairs("0 1\n2 2\n")
        r, out = self.verify(p)
        self.assertEqual(out["self_joins"], 1)
        self.assertEqual(out["illegal"], 1)
        self.assertNotEqual(r.returncode, 0)

    def test_reversed_and_out_of_range_detected(self):
        p = self.pairs("5 2\n0 99\n-1 3\n")
        r, out = self.verify(p)
        self.assertEqual(out["reversed"], 1)
        self.assertEqual(out["out_of_range"], 2)
        self.assertEqual(out["illegal"], 3)
        self.assertNotEqual(r.returncode, 0)

    def test_bad_line_detected(self):
        p = self.pairs("0 1\nhello\n1 2 3\n")
        r, out = self.verify(p)
        self.assertEqual(out["bad_lines"], 2)
        self.assertNotEqual(r.returncode, 0)

    def test_order_change_ordered_vs_unordered_compare(self):
        a = self.pairs("0 1\n0 2\n1 2\n", "a.txt")
        b = self.pairs("0 2\n1 2\n0 1\n", "b.txt")
        ro = run(["compare", "--left", str(a), "--right", str(b), "--ordered",
                  "--tmp", str(self.dir)])
        self.assertNotEqual(ro.returncode, 0)  # different byte order
        ru = run(["compare", "--left", str(a), "--right", str(b),
                  "--tmp", str(self.dir)])
        self.assertEqual(ru.returncode, 0)  # same multiset
        self.assertTrue(json.loads(ru.stdout)["equal"])

    def test_endpoint_predictions_match_evaluate(self):
        # endpoints: 0 and 3; pairs touch them (a<b canonical, as DiskJoin writes)
        p = self.pairs("0 1\n0 2\n3 4\n0 3\n")
        gt = self.dir / "gt.txt"; gt.write_text("3 1 4\n")
        diag = self.dir / "diag.txt"; diag.write_text("0 2 1 2\n")
        r, out = self.verify(p, gt=gt, diag=diag, dup_mode="external-sort")
        rows, _ = endpoint_counts({0: {1, 2}, 3: {4}}, p, N)
        for e in ("0", "3"):
            self.assertEqual(out["sampled_endpoints"][e]["predicted"], rows[int(e)]["predicted"])
            self.assertEqual(out["sampled_endpoints"][e]["tp"], rows[int(e)]["tp"])
            self.assertEqual(out["sampled_endpoints"][e]["fp"], rows[int(e)]["fp"])


if __name__ == "__main__":
    unittest.main()
