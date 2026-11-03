#!/usr/bin/env python3
"""Offline cache-policy analysis of a GATE4A_CACHE_TRACE (Gate 4B readiness).

Reads the access-only trace (lines "A seq id hit") and simulates, for the SAME
capacity and access sequence:
  * Belady (OPT): evict the bucket with the farthest next use
  * LRU: evict the least recently used bucket

Reports miss counts per policy. This is a measurement-infrastructure
feasibility check (the trace discriminates policies), NOT a performance
ablation of the C++ implementation.
"""
import argparse
import json


def simulate(trace, capacity, policy):
    cache = set()
    last_use = {}
    miss = hit = 0
    seq = []
    for (s, bid) in trace:
        seq.append(bid)
    # next-use positions for Belady
    next_use = [None] * len(seq)
    last = {}
    for i in range(len(seq) - 1, -1, -1):
        next_use[i] = last.get(seq[i])
        last[seq[i]] = i
    clock = 0
    for i, bid in enumerate(seq):
        if bid in cache:
            hit += 1
        else:
            miss += 1
            if len(cache) < capacity:
                cache.add(bid)
            else:
                if policy == "belady":
                    victim, far = None, -1
                    for c in cache:
                        nu = next_use[i + 1] if False else None
                        # find next use of c after i
                        j = i + 1
                        # precomputed via next-use chains would be faster; n is small
                        while j < len(seq) and seq[j] != c:
                            j += 1
                        nu = j if j < len(seq) else float("inf")
                        if nu > far:
                            far, victim = nu, c
                    cache.remove(victim)
                else:  # lru
                    victim = min(cache, key=lambda c: last_use.get(c, -1))
                    cache.remove(victim)
                cache.add(bid)
        last_use[bid] = clock
        clock += 1
    return {"policy": policy, "capacity": capacity, "accesses": len(seq),
            "hit": hit, "miss": miss,
            "miss_rate": miss / len(seq) if seq else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--capacity", type=int, required=True)
    ap.add_argument("--out")
    args = ap.parse_args()

    trace = []
    with open(args.trace) as f:
        for line in f:
            parts = line.split()
            if parts and parts[0] == "A":
                trace.append((int(parts[1]), int(parts[2])))

    res = [simulate(trace, args.capacity, "belady"),
           simulate(trace, args.capacity, "lru")]
    print(json.dumps(res, indent=1))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(res, f, indent=1)


if __name__ == "__main__":
    main()
