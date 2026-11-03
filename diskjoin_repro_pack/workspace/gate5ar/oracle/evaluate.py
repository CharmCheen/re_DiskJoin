"""Endpoint-cluster percentile bootstrap, conditional on the fixed graph/threshold."""
import argparse
import hashlib
import json
import random
from pathlib import Path
from sample_endpoints import split_ids


def load_gt(path, n):
    result = {}
    for line in Path(path).read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        e, k, *ids = map(int, line.split())
        if (e in result or not 0 <= e < n or k != len(ids) or
                len(set(ids)) != k or e in ids or any(not 0 <= j < n for j in ids)):
            raise ValueError("invalid GT row")
        result[e] = set(ids)
    if not result:
        raise ValueError("empty GT")
    return result


def endpoint_counts(gt, pair_path, n):
    found = {e: set() for e in gt}
    seen = set()
    with Path(pair_path).open() as source:
        for line in source:
            a, b = map(int, line.split())
            if not 0 <= a < b < n:
                raise ValueError("illegal pair")
            key = a * n + b
            if key in seen:
                raise ValueError("duplicate pair")
            seen.add(key)
            if a in found:
                found[a].add(b)
            if b in found:
                found[b].add(a)
    rows = {e: dict(endpoint=e, gt=len(gt[e]), tp=len(found[e] & gt[e]),
                    fp=len(found[e] - gt[e]), predicted=len(found[e])) for e in gt}
    return rows, len(seen)


def metrics(rows):
    total_gt = sum(r["gt"] for r in rows)
    tp = sum(r["tp"] for r in rows)
    predicted = sum(r["predicted"] for r in rows)
    nonempty = [r["tp"] / r["gt"] for r in rows if r["gt"]]
    return dict(neighbor_weighted_recall=tp / total_gt if total_gt else None,
                nonempty_endpoint_mean_recall=sum(nonempty) / len(nonempty) if nonempty else None,
                precision=tp / predicted if predicted else None)


def quantile(values, p):
    values = sorted(values)
    x = (len(values) - 1) * p
    lo = int(x)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)


def bootstrap(rows, replicates=5000, seed=2026110303):
    if len(rows) < 2 or replicates < 100:
        raise ValueError("need >=2 endpoints and >=100 replicates")
    point = metrics(rows)
    samples = {k: [] for k in point}
    rng = random.Random(seed)
    for _ in range(replicates):
        draw = [rows[rng.randrange(len(rows))] for _ in rows]
        for key, value in metrics(draw).items():
            if value is not None:
                samples[key].append(value)
    result = {}
    for key, value in point.items():
        values = samples[key]
        valid = len(values)
        ci = [quantile(values, .025), quantile(values, .975)] if valid >= .95 * replicates else None
        result[key] = dict(estimate=value, percentile95=ci, valid_replicates=valid,
                           undefined_replicates=replicates-valid,
                           degenerate=bool(ci and ci[0] == ci[1]))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gt", required=True, type=Path)
    p.add_argument("--diagnostic-gt", required=True, type=Path)
    p.add_argument("--split", required=True, type=Path)
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--replicates", type=int, default=5000)
    p.add_argument("--m", type=int, default=272)
    a = p.parse_args()
    if not 1 <= a.m <= 4095:
        raise ValueError("m outside [1,4095]")
    design = json.loads((a.split / "manifest.json").read_text())
    n = design["n"]
    c = set(map(int, (a.split / "calibration.txt").read_text().split()))
    e = set(map(int, (a.split / "evaluation.txt").read_text().split()))
    for name, digest in design["sha256"].items():
        if hashlib.sha256((a.split / name).read_bytes()).hexdigest() != digest:
            raise ValueError("split hash mismatch")
    expected_c, expected_e = split_ids(n, design["calibration_n"], design["evaluation_n"])
    if c != set(expected_c) or e != set(expected_e):
        raise ValueError("split differs from fixed seeded design")
    if c & e or 0 in c | e or len(e) != design["evaluation_n"] or len(c) != design["calibration_n"]:
        raise ValueError("invalid holdout split")
    gt = load_gt(a.gt, n)
    diag = load_gt(a.diagnostic_gt, n)
    if set(gt) != e or set(diag) != {0}:
        raise ValueError("GT endpoint mismatch")
    rows, npairs = endpoint_counts({**gt, **diag}, a.pairs, n)
    evaluation = [rows[i] for i in sorted(e)]
    result = dict(design=design, threshold_squared=a.m*a.m, distance_rule="strict squared L2 < threshold",
                  input_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [a.gt, a.diagnostic_gt, a.pairs, a.split / "manifest.json"]},
                  bootstrap_unit="whole endpoint, including empty GT endpoints",
                  bootstrap_seed=2026110303, bootstrap_replicates=a.replicates,
                  intervals="approximate percentile bootstrap; no finite-population correction",
                  metrics=bootstrap(evaluation, a.replicates), endpoints=evaluation,
                  empty_gt_endpoints=sum(r["gt"] == 0 for r in evaluation),
                  sampled_false_positives=sum(r["fp"] for r in evaluation),
                  diagnostic_zero=rows[0], total_output_pairs=npairs,
                  limits=["Conditional on calibration split, fixed threshold and graph; no full-join exact Recall claim.",
                          "Two sampled endpoints may share a pair; deduplication does not create independent pair trials.",
                          "Heavy tails and 200 endpoints can make percentile coverage poor; no guaranteed 95% coverage.",
                          "Precision is endpoint-incidence weighted. A [1,1] interval with no observed FP cannot exclude rare population FP.",
                          "No dataset-level or graph-construction uncertainty; vector 0 is excluded from all estimates."])
    with a.out.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    if result["sampled_false_positives"] or rows[0]["fp"]:
        raise SystemExit("STOP: observed false positives (result saved)")
    if any(v["estimate"] is None or v["percentile95"] is None for v in result["metrics"].values()):
        raise SystemExit("STOP: undefined metric/unstable bootstrap (result saved)")


if __name__ == "__main__":
    main()
