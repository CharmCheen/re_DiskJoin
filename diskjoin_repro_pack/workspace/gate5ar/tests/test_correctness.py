import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
from sample_endpoints import split_ids
from evaluate import bootstrap, endpoint_counts, load_gt, metrics
sys.path.insert(0, str(ROOT / "scripts"))
from validate_run import validate


def independent_distance(a, b):
    # Algebraically separate from C++ coordinate-difference accumulation.
    return sum(v*v for v in a) + sum(v*v for v in b) - 2*sum(x*y for x, y in zip(a, b))


class OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.path = Path(cls.temp.name)
        cls.binary = cls.path / "oracle"
        compiler = os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++")
        if not compiler:
            raise RuntimeError("C++ compiler required")
        subprocess.run([compiler, "-std=c++11", "-O2", "-Wall", "-Wextra", "-Wno-unknown-pragmas",
                        str(ROOT / "oracle/gt_calib.cpp"), "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, rows):
        d = Path(tempfile.mkdtemp(dir=self.path))
        data = d / "data.bvecs"
        data.write_bytes(b"".join(struct.pack("<I", 128) + bytes(row) for row in rows))
        ids = d / "ids.txt"
        ids.write_text("".join(f"{i}\n" for i in range(len(rows))))
        return d, data, ids

    def test_last_four_dimensions_calib_and_gt(self):
        rows = [[0]*128, [0]*124+[255]*4, [0]*127+[1], [0]*127+[2]]
        d, data, ids = self.fixture(rows)
        out = d / "gt.txt"
        subprocess.run([str(self.binary), "gt", str(data), str(ids), "2", str(out)], check=True)
        actual = load_gt(out, len(rows))
        expected = {i: {j for j, b in enumerate(rows) if i != j and independent_distance(a, b) < 4}
                    for i, a in enumerate(rows)}
        self.assertEqual(actual, expected)
        self.assertNotIn(1, actual[0])
        self.assertNotIn(3, actual[0])  # strict threshold boundary
        calib = subprocess.check_output([str(self.binary), "calib", str(data), str(ids), "2"], text=True)
        self.assertEqual(int(calib.splitlines()[1].split()[3]), sum(map(len, expected.values())))
        self.assertEqual(independent_distance(rows[0], rows[1]), 260100)

    def test_frozen_oracle_header_offset_reproducer(self):
        old = (ROOT.parent / "gate5a/oracle/gt_calib.cpp").read_text()
        start = old.index("static inline int32_t d2(")
        function = old[start:old.index("\n}", start)+2]
        source = self.path / "old_offset.cpp"
        source.write_text('#include <cstdint>\n#include <cstdio>\nstatic const unsigned D=128;\n' + function +
                          '\nint main(){uint8_t a[132]={128},b[132]={128};'
                          'for(int i=128;i<132;++i)b[i]=255;'
                          'printf("%d\\n",d2(a,b));}\n')
        binary = self.path / "old_offset"
        compiler = os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++")
        subprocess.run([compiler, "-std=c++11", str(source), "-o", str(binary)], check=True)
        self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(), "0")
        self.assertEqual(independent_distance([0]*128, [0]*124+[255]*4), 260100)

    def test_random_cross_implementation(self):
        rng = random.Random(91)
        rows = [[rng.randrange(32) for _ in range(128)] for _ in range(24)]
        d, data, ids = self.fixture(rows)
        out = d / "gt.txt"
        subprocess.run([str(self.binary), "gt", str(data), str(ids), "150", str(out)], check=True)
        expected = {i: {j for j, b in enumerate(rows) if i != j and independent_distance(a, b) < 22500}
                    for i, a in enumerate(rows)}
        self.assertEqual(load_gt(out, len(rows)), expected)

    def test_reject_bad_inputs_and_overwrite(self):
        d, data, ids = self.fixture([[0]*128, [1]*128])
        out = d / "gt.txt"
        args = [str(self.binary), "gt", str(data), str(ids), "272", str(out)]
        subprocess.run(args, check=True)
        self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
        for content in [b"", struct.pack("<I", 127)+bytes(128), struct.pack("<I", 128)+bytes(127)]:
            data.write_bytes(content)
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
        data.write_bytes(struct.pack("<I", 128)+bytes(128))
        for text in ["0\n0\n", "-1\n", "1\n", "junk\n", ""]:
            ids.write_text(text)
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)


class StatisticsTests(unittest.TestCase):
    def test_staged_server_validator_rejects_bad_invariant_and_rss(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as t:
            root = Path(t)
            (root / "diagnostic.txt").write_text("0 1 1\n")
            normal = root / "normal"
            normal.mkdir()
            for name in ["knn.txt", "tasks.txt", "trace.txt", "data.metadata", "data.hnsw", "data.clusters"]:
                (normal / name).write_bytes(b"fixture")
            (normal / "pairs.txt").write_text("0 1\n")
            log = ("[gate3-inv] perm_ok=1 upper_triangle_ok=1 empty_tasks=0 head_mismatch=0 self_missing=0 bucket_sum=100000\n"
                   "[gate3-stat] sampled_count=1 gt=1\n[gate4a-cache] miss=1\n[gate4b1-io] read_calls=1\n")
            (normal / "stderr.log").write_text(log)
            (normal / "time.log").write_text("Maximum resident set size (kbytes): 100\n")
            self.assertTrue(validate(root, normal, "normal")["legacy_baseline_identical"])
            (normal / "stderr.log").write_text(log.replace("head_mismatch=0", "head_mismatch=1"))
            with self.assertRaises(ValueError): validate(root, normal, "normal")
            (normal / "stderr.log").write_text(log)
            (normal / "time.log").write_text("Maximum resident set size (kbytes): 999999999\n")
            with self.assertRaises(ValueError): validate(root, normal, "normal")

    def test_sampler_and_evaluator_cli_diagnostic_is_separate(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as t:
            folder = Path(t)
            split = folder / "split"
            subprocess.run([sys.executable, "-B", str(ROOT / "oracle/sample_endpoints.py"),
                            "--n", "10", "--calibration", "2", "--evaluation", "4", "--out", str(split)], check=True)
            ids = list(map(int, (split / "evaluation.txt").read_text().split()))
            def gt_lines(es):
                return "".join(f"{e} 9 " + " ".join(str(j) for j in range(10) if j != e) + "\n" for e in es)
            (folder / "gt").write_text(gt_lines(ids))
            (folder / "diag").write_text(gt_lines([0]))
            (folder / "pairs").write_text("".join(f"{i} {j}\n" for i in range(10) for j in range(i+1, 10)))
            args = [sys.executable, "-B", str(ROOT / "oracle/evaluate.py"), "--gt", str(folder / "gt"),
                    "--diagnostic-gt", str(folder / "diag"), "--pairs", str(folder / "pairs"),
                    "--split", str(split), "--replicates", "100", "--out", str(folder / "result.json")]
            subprocess.run(args, check=True)
            result = json.loads((folder / "result.json").read_text())
            self.assertEqual(result["metrics"]["neighbor_weighted_recall"]["estimate"], 1)
            self.assertEqual(result["diagnostic_zero"]["endpoint"], 0)
            self.assertNotIn(0, [r["endpoint"] for r in result["endpoints"]])
            (split / "evaluation.txt").write_text("0\n")
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)

    def test_disjoint_reproducible_split(self):
        c, e = split_ids(100000)
        self.assertFalse(set(c) & set(e))
        self.assertNotIn(0, c+e)
        self.assertEqual((c, e), split_ids(100000))
        self.assertEqual((len(c), len(e)), (2000, 200))
        with self.assertRaises(ValueError):
            split_ids(10)

    def test_weighted_mean_precision_and_empty_endpoint(self):
        rows = [dict(gt=100, tp=90, fp=0, predicted=90),
                dict(gt=2, tp=0, fp=0, predicted=0),
                dict(gt=0, tp=0, fp=1, predicted=1)]
        m = metrics(rows)
        self.assertAlmostEqual(m["neighbor_weighted_recall"], 90/102)
        self.assertAlmostEqual(m["nonempty_endpoint_mean_recall"], .45)
        self.assertAlmostEqual(m["precision"], 90/91)
        a = bootstrap(rows, 1000)
        self.assertEqual(a, bootstrap(rows, 1000))
        self.assertGreater(a["neighbor_weighted_recall"]["undefined_replicates"], 0)

    def test_undefined_and_degenerate_intervals(self):
        r = dict(gt=0, tp=0, fp=0, predicted=0)
        result = bootstrap([r, r], 100)
        self.assertIsNone(result["precision"]["estimate"])
        self.assertIsNone(result["precision"]["percentile95"])
        r = dict(gt=1, tp=1, fp=0, predicted=1)
        self.assertTrue(bootstrap([r, r], 100)["precision"]["degenerate"])

    def test_pair_validation_includes_empty_gt_fp(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as t:
            path = Path(t) / "pairs.txt"
            path.write_text("0 1\n")
            rows, _ = endpoint_counts({0:set(), 1:{0}}, path, 2)
            self.assertEqual(rows[0]["fp"], 1)
            for text in ["0 1\n0 1\n", "1 0\n", "0 2\n", "0 0\n"]:
                path.write_text(text)
                with self.assertRaises(ValueError):
                    endpoint_counts({0:set()}, path, 2)


if __name__ == "__main__":
    unittest.main()
