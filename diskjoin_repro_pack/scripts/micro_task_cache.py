#!/usr/bin/env python3
"""Tiny stdlib-only demonstration of the task-order / cache interaction.

This is educational code, NOT a reproduction of DiskJoin's Gorder algorithm.
Assumptions: unit-sized buckets, capacity in buckets, each pair is an atomic task,
all requested buckets must be available by the time its computation begins.
"""
import argparse
import json
from collections import OrderedDict

ORIGINAL = [("A", "B"), ("C", "D"), ("A", "C")]
REORDERED = [("A", "B"), ("A", "C"), ("C", "D")]


def simulate(tasks, capacity=2, policy="belady"):
    if capacity < 2:
        raise ValueError("at least 2 cache slots are needed for pair tasks")
    sequence = [bucket for task in tasks for bucket in task]
    cache = OrderedDict()
    trace = []
    hits = 0
    misses = 0
    for step, bucket in enumerate(sequence):
        victim = None
        if bucket in cache:
            hits += 1
            cache.move_to_end(bucket)
            hit = True
        else:
            misses += 1
            hit = False
            if len(cache) >= capacity:
                if policy == "lru":
                    victim = next(iter(cache))
                elif policy == "belady":
                    # Exactly optimal for a fixed sequence with equal-sized buckets.
                    future = sequence[step + 1:]
                    next_use = {
                        resident: future.index(resident) if resident in future else float("inf")
                        for resident in cache
                    }
                    victim = max(cache, key=lambda key: next_use[key])
                else:
                    raise ValueError("unknown policy: " + policy)
                del cache[victim]
            cache[bucket] = None
        trace.append({"step": step + 1, "bucket": bucket, "hit": hit,
                      "evicted": victim, "cache": list(cache)})
    return {"tasks": [list(t) for t in tasks], "policy": policy,
            "capacity": capacity, "misses": misses, "hits": hits,
            "accesses": len(sequence), "trace": trace}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capacity", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = {f"{name}_{policy}": simulate(tasks, args.capacity, policy)
               for name, tasks in (("original", ORIGINAL), ("reordered", REORDERED))
               for policy in ("belady", "lru")}
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for key, entry in results.items():
            print(f"{key:18s} cache_misses={entry['misses']} hits={entry['hits']}")


if __name__ == "__main__":
    main()
