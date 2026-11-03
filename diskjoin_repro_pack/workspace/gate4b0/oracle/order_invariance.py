#!/usr/bin/env python3
"""Gate 4B-0 Task 3 (ablation fairness): verify that the task order override
(identity / fixed-seed random / Gorder-window-override) changes ONLY the slot
placement of buckets and hence the cache access sequence.

Invariants checked per dataset (P1, P3), across runs
  {default, identity, random, window120} + frozen gate4a dumps:
  1. pair sets identical (join output independent of processing order)
  2. task multiset identical: each (target_bucket, tuple(task_list)) appears
     exactly once in every run; only the slot index carrying it differs
  3. cache stats summary table (for the report)

Read-only; consumes gate4b0 run outputs + gate4a frozen dumps.
"""
import json
import sys
from pathlib import Path

WS = Path("/home/qch/DiskJoin/diskjoin_repro_pack/workspace")
G4B0 = WS / "gate4b0" / "runs"

RUNS = {
    "p1": {
        "default": G4B0 / "p1_default",
        "identity": G4B0 / "p1_identity",
        "random": G4B0 / "p1_random",
        "window120": G4B0 / "p1_window120",
        "frozen_pairs": [WS / "gate4a/runs/pairs_p1_eb0.1.txt",
                         WS / "gate4a/runs/pairs_p1_small.txt"],
        "frozen_tasks": WS / "gate4a/runs/tasks_p1_small.txt",
    },
    "p3": {
        "default": G4B0 / "p3_default",
        "identity": G4B0 / "p3_identity",
        "random": G4B0 / "p3_random",
        "window120": G4B0 / "p3_window120",
        "frozen_pairs": [WS / "gate4a/runs/pairs_p3_eb0.1.txt",
                         WS / "gate4a/runs/pairs_p3_small.txt"],
        "frozen_tasks": WS / "gate4a/runs/tasks_p3_small.txt",
    },
}


def read_pairs(path):
    pairs = set()
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                pairs.add((int(parts[0]), int(parts[1])))
    return pairs


def read_tasks(path):
    """Return {slot: (target_bucket, [neighbour...])}."""
    out = {}
    with open(path) as f:
        for line in f:
            parts = [int(x) for x in line.split()]
            slot, target, deg = parts[0], parts[1], parts[2]
            neigh = parts[3:3 + deg]
            assert len(neigh) == deg, f"{path}: degree mismatch at slot {slot}"
            out[slot] = (target, neigh)
    return out


def main():
    results = {}
    ok_all = True
    for ds, spec in RUNS.items():
        res = {"pair_sets": {}, "task_multisets": {}, "task_slot_maps": {},
               "checks": {}}
        for name in ("default", "identity", "random", "window120"):
            run = spec[name]
            res["pair_sets"][name] = read_pairs(run / "pairs.txt")
            tasks = read_tasks(run / "tasks.txt")
            res["task_multisets"][name] = {tuple((t, tuple(n))) for t, n in tasks.values()}
            res["task_slot_maps"][name] = tasks

        # frozen references
        frozen_pair_sets = [read_pairs(p) for p in spec["frozen_pairs"]]
        frozen_tasks = read_tasks(spec["frozen_tasks"])
        frozen_multiset = {(t, tuple(n)) for t, n in frozen_tasks.values()}

        # 1. pair-set invariance across orders (+ frozen)
        sets = list(res["pair_sets"].values()) + frozen_pair_sets
        pair_inv = all(s == sets[0] for s in sets)
        res["checks"]["pair_set_invariant_across_orders_and_frozen"] = pair_inv
        res["pair_count"] = len(sets[0])

        # 2. task-multiset invariance across orders (+ frozen)
        multisets = list(res["task_multisets"].values()) + [frozen_multiset]
        task_inv = all(m == multisets[0] for m in multisets)
        res["checks"]["task_multiset_invariant_across_orders_and_frozen"] = task_inv
        res["task_entry_count"] = len(multisets[0])

        # 3. duplicate (target, list) entries must not exist
        res["checks"]["task_targets_unique"] = (
            len({t for t, _ in multisets[0]}) == len(multisets[0]))

        # 4. per-run slot maps: identity of the 4 maps (slot -> content)
        #    differs (expected: only placement changes), report Hamming-ish
        #    summary: number of slots whose content differs vs default
        d = res["task_slot_maps"]["default"]
        for name in ("identity", "random", "window120"):
            m = res["task_slot_maps"][name]
            same_slot = sum(1 for s in d if d[s] == m.get(s))
            res["checks"][f"slots_same_content_vs_default[{name}]"] = same_slot

        ok = pair_inv and task_inv and res["checks"]["task_targets_unique"]
        res["ok"] = ok
        ok_all = ok_all and ok
        results[ds] = res
        print(f"[{ds}] pair_set_invariant={pair_inv} "
              f"task_multiset_invariant={task_inv} "
              f"pairs={res['pair_count']} task_entries={res['task_entry_count']} "
              f"slots_same_vs_default="
              f"{res['checks']['slots_same_content_vs_default[identity]']}/"
              f"{res['checks']['slots_same_content_vs_default[random]']}/"
              f"{res['checks']['slots_same_content_vs_default[window120]']}")

    results["ok_all"] = ok_all
    out = WS / "gate4b0" / "results" / "order_invariance.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=1, default=list)
    print(f"{'PASS' if ok_all else 'FAIL'} -> {out}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
