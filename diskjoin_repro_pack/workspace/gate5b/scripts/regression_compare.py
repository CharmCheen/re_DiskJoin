#!/usr/bin/env python3
"""Gate 5B 100K output-consistency comparator.

Checks, for the bounded gate5b regression run:
  * normal vs prefetch_off output artifacts byte-identical;
  * both byte-identical to the frozen Gate 5A baseline;
  * pairs are legal (0 <= a < b < n), unique, and the expected count;
  * join invariants in stderr (bucket_sum=n, perm_ok, upper_triangle_ok,
    empty_tasks=head_mismatch=self_missing=0);
  * no sanitizer/error strings.

Exit 0 iff every check passes.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ART = ["knn.txt", "tasks.txt", "pairs.txt", "trace.txt",
       "data.metadata", "data.hnsw", "data.clusters"]
N = 100000
EXPECTED_PAIRS = 3855811


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    root = Path(sys.argv[1])          # runs/step2_100k
    base = Path(sys.argv[2])          # frozen gate5a/runs/r1_default
    failures = []
    result = {"artifacts": {}, "checks": {}}

    hashes = {}
    for mode in ["normal", "prefetch_off"]:
        run = root / mode
        hashes[mode] = {}
        for name in ART:
            f = run / name
            if not f.exists():
                failures.append(f"missing {mode}/{name}")
                hashes[mode][name] = None
            else:
                hashes[mode][name] = sha(f)

    baseline_hashes = {name: sha(base / name) for name in ["knn.txt", "tasks.txt",
                                                           "pairs.txt", "trace.txt"]}

    # 1. cross-mode identity
    result["checks"]["normal_vs_prefetch_off_identical"] = all(
        hashes["normal"][n] == hashes["prefetch_off"][n] for n in ART)
    if not result["checks"]["normal_vs_prefetch_off_identical"]:
        failures.append("normal vs prefetch_off artifact mismatch")

    # 2. versus frozen baseline (join outputs)
    result["checks"]["baseline_identical"] = all(
        hashes["normal"][n] == baseline_hashes[n] for n in baseline_hashes)
    if not result["checks"]["baseline_identical"]:
        failures.append("artifact differs from frozen Gate 5A baseline")

    # 3. pair legality / uniqueness / count
    seen = set()
    n_lines = illegal = dup = 0
    with (root / "normal" / "pairs.txt").open() as fh:
        for line in fh:
            a, b = map(int, line.split())
            n_lines += 1
            if not (0 <= a < b < N):
                illegal += 1
            k = (a, b)
            if k in seen:
                dup += 1
            else:
                seen.add(k)
    result["checks"]["pairs_lines"] = n_lines
    result["checks"]["pairs_unique"] = len(seen)
    result["checks"]["pairs_illegal"] = illegal
    result["checks"]["pairs_duplicate"] = dup
    if n_lines != EXPECTED_PAIRS:
        failures.append(f"pair count {n_lines} != expected {EXPECTED_PAIRS}")
    if illegal or dup:
        failures.append("illegal/duplicate pair present")

    # 4. invariants + no sanitizer
    for mode in ["normal", "prefetch_off"]:
        text = (root / mode / "stderr.log").read_text()
        if re.search(r"AddressSanitizer|LeakSanitizer|runtime error:", text):
            failures.append(f"{mode}: sanitizer finding")
        inv = next((x for x in text.splitlines() if x.startswith("[gate3-inv]")), None)
        if inv is None:
            failures.append(f"{mode}: no [gate3-inv] line")
        else:
            kv = dict(re.findall(r"(\w+)=(\d+)", inv))
            if kv.get("bucket_sum") != str(N):
                failures.append(f"{mode}: bucket_sum={kv.get('bucket_sum')} != {N}")
            for k in ["perm_ok", "upper_triangle_ok"]:
                if kv.get(k) != "1":
                    failures.append(f"{mode}: {k}={kv.get(k)}")
            for k in ["empty_tasks", "head_mismatch", "self_missing"]:
                if kv.get(k) != "0":
                    failures.append(f"{mode}: {k}={kv.get(k)}")
        rss = int(re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)",
                            (root / mode / "time.log").read_text()).group(1))
        result["checks"][f"{mode}_rss_kb"] = rss
        if rss > 4 * 1024 * 1024:
            failures.append(f"{mode}: RSS {rss} KB exceeds 4 GiB")

    result["artifacts"]["normal"] = hashes["normal"]
    result["artifacts"]["prefetch_off"] = hashes["prefetch_off"]
    result["artifacts"]["baseline"] = baseline_hashes
    result["failures"] = failures
    result["PASS"] = not failures
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
