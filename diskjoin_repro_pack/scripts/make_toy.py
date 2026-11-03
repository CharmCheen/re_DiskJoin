#!/usr/bin/env python3
"""Generate deterministic synthetic .fbin data and DiskJoin config (stdlib only).

Small-data GT follows the reference code's *sampled* metric: count pairs for
which at least one endpoint has ID divisible by 100000. This GT is not a full
join result / exhaustive all-pairs accuracy evaluation.
"""
import argparse
import json
import math
import random
import struct
from pathlib import Path


def build(args):
    if args.n < 1000 or args.n % 1000:
        raise SystemExit("n must be >=1000 and divisible by 1000 (reference batch assumptions)")
    if args.n >= 100000:
        raise SystemExit("minimal GT generator supports n < 100000 only")
    if args.clusters > args.n or args.clusters < 2:
        raise SystemExit("clusters must satisfy 2 <= clusters <= n")
    if args.K <= 0 or args.K > args.clusters:
        raise SystemExit("K must satisfy 1 <= K <= clusters")
    if args.dimension % 8:
        raise SystemExit("dimension must be divisible by 8 for the reference AVX2 distance path")
    if not (0.0 < args.mem_budget <= 1.0):
        raise SystemExit("toy mem_budget must be between 0 and 1 GiB")
    rng = random.Random(args.seed)
    centers = [[rng.uniform(-3.0, 3.0) for _ in range(args.dimension)]
               for _ in range(args.classes)]
    root = Path(__file__).resolve().parents[1]
    out = root / "workspace" / "toy"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "toy.fbin"
    # Collect sampled vectors only. Currently n < 100000 => sample IDs = {0}.
    sampled = {}
    gt = 0
    eps2 = args.epsilon ** 2
    first = None
    with path.open("wb") as f:
        f.write(struct.pack("<II", args.n, args.dimension))
        for i in range(args.n):
            c = centers[i % args.classes]
            x = [float(z + rng.gauss(0.0, args.noise)) for z in c]
            # Make vector rounding match the binary fbin data.
            vals = struct.unpack(f"<{args.dimension}f", struct.pack(f"<{args.dimension}f", *x))
            f.write(struct.pack(f"<{args.dimension}f", *vals))
            if i == 0:
                first = vals
            elif args.n < 100000:
                dist2 = sum((a-b)*(a-b) for a,b in zip(first,vals))
                if dist2 < eps2:
                    gt += 1
            if i % 100000 == 0:
                sampled[i] = vals
    if gt == 0:
        raise SystemExit("GT=0; adjust epsilon/noise before running")
    config = out / "toy.config"
    # ConfigReader reads alternating whitespace tokens in fixed order.
    lines = {
        "data_file": path,
        "radius": format(eps2, ".9g"),
        "cluster_num": args.clusters,
        "cluster_file": out / "toy.clusters",
        "metadata_file": out / "toy.metadata",
        "hnsw_file": out / "toy.hnsw",
        "K": args.K,
        "mem_budget": args.mem_budget,
        "error_bound": args.error_bound,
        "gt": gt,
    }
    config.write_text("".join(f"{k:<16} {v}\n" for k,v in lines.items()), encoding="utf-8")
    metadata = {"n": args.n, "dimension": args.dimension, "classes": args.classes,
                "epsilon": args.epsilon, "radius_squared": eps2, "gt_sampled": gt,
                "sample_ids": sorted(sampled), "seed": args.seed,
                "note": "Reference counts only pairs incident to ids % 100000 == 0; this is a sampled GT."}
    (out / "toy_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"fbin": str(path), "config": str(config), **metadata}, indent=2))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--n",type=int,default=12000)
    p.add_argument("--dimension",type=int,default=16)
    p.add_argument("--classes",type=int,default=20)
    p.add_argument("--clusters",type=int,default=120)
    p.add_argument("--K",type=int,default=24)
    p.add_argument("--epsilon",type=float,default=0.25)
    p.add_argument("--noise",type=float,default=0.02)
    p.add_argument("--mem-budget",dest="mem_budget",type=float,default=0.1)
    p.add_argument("--error-bound",dest="error_bound",type=float,default=0.1)
    p.add_argument("--seed",type=int,default=283)
    build(p.parse_args())

if __name__=="__main__":main()
