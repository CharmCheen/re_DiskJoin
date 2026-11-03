import argparse
import hashlib
import json
import re
from pathlib import Path


def validate(root, baseline=None, through_mode="prefetch_off", expected_n=None):
    if expected_n is None:
        raise ValueError("expected_n (from validated data manifest) is required")
    diag_gt = int((root / "diagnostic.txt").read_text().split()[1])
    digests = {}
    modes = ["normal", "asan", "prefetch_off"]
    for mode in modes[:modes.index(through_mode)+1]:
        run = root / mode
        text = (run / "stderr.log").read_text()
        if "ERROR: AddressSanitizer" in text or "runtime error:" in text:
            raise ValueError("sanitizer finding")
        inv = next(x for x in text.splitlines() if x.startswith("[gate3-inv]"))
        kv = dict(re.findall(r"(\w+)=(\d+)", inv))
        for key in ["perm_ok", "upper_triangle_ok"]:
            if kv.get(key) != "1": raise ValueError(f"{mode}: {key}")
        for key in ["empty_tasks", "head_mismatch", "self_missing"]:
            if kv.get(key) != "0": raise ValueError(f"{mode}: {key}")
        if kv.get("bucket_sum") != str(expected_n): raise ValueError("wrong cardinality")
        stat = next(x for x in text.splitlines() if x.startswith("[gate3-stat]"))
        sampled = int(re.search(r"sampled_count=(\d+)", stat).group(1))
        if int(re.search(r"gt=(\d+)", stat).group(1)) != diag_gt:
            raise ValueError("wrong diagnostic denominator")
        with (run / "pairs.txt").open() as source:
            count_zero = sum(line.startswith("0 ") for line in source)
        if sampled != count_zero: raise ValueError("diagnostic count mismatch")
        cache = next(x for x in text.splitlines() if x.startswith("[gate4a-cache]"))
        io = next(x for x in text.splitlines() if x.startswith("[gate4b1-io]"))
        if re.search(r"miss=(\d+)", cache).group(1) != re.search(r"read_calls=(\d+)", io).group(1):
            raise ValueError("miss/read count mismatch")
        digests[mode] = {}
        for name in ["knn.txt", "tasks.txt", "pairs.txt", "trace.txt", "data.metadata", "data.hnsw", "data.clusters"]:
            digest = hashlib.sha256((run / name).read_bytes()).hexdigest()
            digests[mode][name] = digest
            if mode != "normal" and digest != digests["normal"][name]:
                raise ValueError(f"output/artifact regression: {mode}/{name}")
        time_log = (run / "time.log").read_text()
        rss = int(re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", time_log).group(1))
        if rss > 12*1024*1024: raise ValueError("RSS exceeds 12 GiB envelope")
    return dict(output_and_bucket_artifacts_identical=True, sha256=digests,
                legacy_baseline_identical=(all(
                    hashlib.sha256((baseline / name).read_bytes()).hexdigest() == digests["normal"][name]
                    for name in ["knn.txt", "tasks.txt", "pairs.txt", "trace.txt"])
                    if baseline is not None else None),
                physical_ssd_io="UNVERIFIED", performance_effect="UNVERIFIED: correctness dumps enabled")


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("root", type=Path)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--through-mode", choices=["normal", "asan", "prefetch_off"], default="prefetch_off")
    p.add_argument("--manifest", type=Path, required=True, help="validated data manifest JSON (provides n)")
    a = p.parse_args()
    expected_n = int(json.loads(a.manifest.read_text())["n"])
    result = validate(a.root, a.baseline, a.through_mode, expected_n)
    print(json.dumps(result, indent=2))
    if result["legacy_baseline_identical"] is False:
        raise SystemExit("STOP: functional regression versus frozen Gate5A dumps")
