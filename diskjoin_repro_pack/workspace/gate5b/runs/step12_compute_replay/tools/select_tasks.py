#!/usr/bin/env python3
"""Step 12 — deterministic stratified task selection from the REAL 1M task graph.

Reads the step11 metadata (bucket sizes) and the real task dump tasks.txt
(line i = "<slot> <target_bucket> <deg> <nb0=nb_self> <nb1> ..."), computes the
EXACT number of point-point distance calls each slot would execute in the join
compute loop:

    cand(slot) = C(n_target, 2) + n_target * sum_{k>=1} n_neighbor_k

and picks fixed slots at the 10th / 50th / 95th percentile of that volume
(small / medium / large). Deterministic, no randomness. Writes:
  inputs/replay_tasks.txt   (slot, target, cand, deg)   <- the fixed input list
"""
import os
import struct

BASE = "/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b/runs/step12_compute_replay"
META = "/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b/runs/step11_hotspot_profile/graph/data.metadata"
TASKS = "/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b/runs/step11_hotspot_profile/runs/profile_10pct/tasks.txt"

# --- metadata: n,d,cluster_num,max_points + bucket_sizes[cluster_num] + ... ---
with open(META, "rb") as f:
    n, d, cluster_num, max_points = struct.unpack("<4Q", f.read(32))
    bs = struct.unpack("<%dQ" % cluster_num, f.read(8 * cluster_num))
print(f"metadata: n={n} d={d} cluster_num={cluster_num} max_points={max_points}")
print(f"sum(bucket_sizes)={sum(bs)}")

# --- tasks ---
slots = []
with open(TASKS) as f:
    for line in f:
        p = line.split()
        i = int(p[0]); target = int(p[1]); deg = int(p[2]); nb = [int(x) for x in p[3:]]
        assert len(nb) == deg, (i, deg, len(nb))
        assert nb[0] == target
        cross = sum(bs[x] for x in nb[1:])
        n_t = bs[target]
        cand = n_t * (n_t - 1) // 2 + n_t * cross
        slots.append((i, target, cand, deg, n_t, cross))
print(f"tasks: {len(slots)}  (expected cluster_num={cluster_num})")

order = sorted(slots, key=lambda s: s[2])
def pick(pct):
    idx = int(pct / 100.0 * (len(order) - 1) + 0.5)
    return order[idx]

chosen = [("small", pick(10)), ("medium", pick(50)), ("large", pick(95))]
lines = []
lines.append(f"# selection rule: fixed percentile of exact candidate count "
             f"cand = C(n_target,2) + n_target*sum(neighbour sizes)")
lines.append(f"# metadata={META}")
lines.append("# label\tslot\ttarget\tcand\tdeg\tn_target\tcross_neighbour_vectors")
for label, (i, target, cand, deg, n_t, cross) in chosen:
    lines.append(f"{label}\t{i}\t{target}\t{cand}\t{deg}\t{n_t}\t{cross}")
    print(f"  {label:<7} slot={i:<4} target={target:<4} cand={cand:<12} deg={deg:<3} n_target={n_t:<5} cross={cross}")

tot = sum(c[1][2] for c in chosen)
print(f"total candidates over chosen tasks (one replay pass) = {tot:,}")
allc = [s[2] for s in slots]
print(f"cand distribution: min={min(allc):,} p50={order[len(order)//2][2]:,} p95={order[int(0.95*len(order))][2]:,} max={max(allc):,}")

os.makedirs(os.path.join(BASE, "inputs"), exist_ok=True)
with open(os.path.join(BASE, "inputs", "replay_tasks.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
print("wrote inputs/replay_tasks.txt")
