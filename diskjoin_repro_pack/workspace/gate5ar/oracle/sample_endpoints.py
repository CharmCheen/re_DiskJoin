"""Fixed disjoint calibration/evaluation split; zero is diagnostic only."""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path


def split_ids(n, calibration=2000, evaluation=200, calib_seed=2026110301,
              eval_seed=2026110302):
    if min(calibration, evaluation) < 1 or calibration + evaluation > n - 1:
        raise ValueError("insufficient nonzero population")
    c = sorted(random.Random(calib_seed).sample(range(1, n), calibration))
    excluded = set(c)
    remaining = [i for i in range(1, n) if i not in excluded]
    e = sorted(random.Random(eval_seed).sample(remaining, evaluation))
    return c, e


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100000)
    p.add_argument("--calibration", type=int, default=2000)
    p.add_argument("--evaluation", type=int, default=200)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    c, e = split_ids(a.n, a.calibration, a.evaluation)
    a.out.mkdir(parents=True, exist_ok=False)
    for name, ids in [("calibration.txt", c), ("evaluation.txt", e), ("diagnostic.txt", [0])]:
        (a.out / name).write_text("".join(f"{i}\n" for i in ids))
    manifest = dict(n=a.n, dimension=128, calibration_n=len(c), evaluation_n=len(e),
                    calibration_seed=2026110301, evaluation_seed=2026110302,
                    diagnostic=[0], overlap=0, python=sys.version,
                    design="SRS without replacement from 1..n-1; evaluation from calibration complement",
                    inference_population="conditional on calibration: nonzero calibration complement",
                    limitation="Endpoint holdout shares the same vector corpus and graph; no dataset-level replication.")
    manifest["sha256"] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in a.out.glob("*.txt")}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
