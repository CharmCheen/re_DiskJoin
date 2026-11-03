#!/usr/bin/env python3
"""Gate 4A synthetic workload generator (W1 overlapping / W2 nonuniform).

Pure stdlib, deterministic per seed. Mirrors scripts/make_toy.py conventions:
  * .fbin = <n:u32><d:u32> + n*d float32 little-endian (values rounded through
    float32 exactly like the file content);
  * config tokens in the fixed ConfigReader order, absolute paths;
  * config `gt` field = |{j != 0 : sq_l2(x_0, x_j) < radius}| (diagnostic
    only; the reference divides its sampled count by it).

Modes
  W1  overlapping Gaussian mixture: `classes` centers uniform in
      [-box, box]^d, per-coordinate noise sigma (equal class sizes).
  W2  nonuniform: Zipf-like class sizes, per-class sigma drawn from a
      tight/medium/loose mix, plus `boundary_frac` of vectors placed at
      controlled distance t*epsilon from a same-class anchor with
      t in a grid around 1.0 (margins recorded after float32 rounding).

Every invocation writes:
  <out>/<name>.fbin          data
  <out>/<name>_meta.json     generator parameters + distance-distribution
                             stats + (W2) boundary-vector margin table
and with --radius also:
  <out>/<name>.config        DiskJoin config (gt = ID-0 neighbourhood size)

Distance stats (always computed, from the in-memory float32 values):
  within-class pairwise sq-L2 quantiles (sampled), cross-class random-pair
  quantiles, used to pick `radius` before freezing a pilot config.
"""
import argparse
import json
import math
import random
import struct
import sys
from pathlib import Path


def f32round(vals):
    return list(struct.unpack("<%df" % len(vals), struct.pack("<%df" % len(vals), *vals)))


def sq_l2(a, b):
    s = 0.0
    for x, y in zip(a, b):
        dx = x - y
        s += dx * dx
    return s


def quantiles(xs, qs=(0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)):
    if not xs:
        return {}
    ys = sorted(xs)
    out = {}
    for q in qs:
        k = min(len(ys) - 1, max(0, int(q * (len(ys) - 1) + 0.5)))
        out["p%02d" % round(q * 100)] = ys[k]
    return out


def gen_W1(args, rng):
    """Equal-size overlapping Gaussian mixture."""
    if args.n % args.classes:
        raise SystemExit("W1 requires n %% classes == 0 (got n=%d classes=%d)"
                          % (args.n, args.classes))
    per = args.n // args.classes
    centers = [f32round([rng.uniform(-args.box, args.box) for _ in range(args.d)])
              for _ in range(args.classes)]
    vecs, labels = [], []
    for i in range(args.n):
        c = centers[i % args.classes]
        x = f32round([z + rng.gauss(0.0, args.sigma) for z in c])
        vecs.append(x)
        labels.append(i % args.classes)
    meta_extra = {"centers": centers}
    return vecs, labels, meta_extra


def gen_W2(args, rng):
    """Zipf-ish sizes, sigma mix, boundary vectors at t*epsilon."""
    classes = args.classes
    # Zipf-like weights: class 0 heaviest. Sizes sum exactly to n.
    weights = [1.0 / (i + 1) ** 0.9 for i in range(classes)]
    total_w = sum(weights)
    sizes = [max(2, int(round(args.n * w / total_w))) for w in weights]
    # fix rounding drift on the largest class
    sizes[0] += args.n - sum(sizes)
    if min(sizes) < 2 or sum(sizes) != args.n:
        raise SystemExit("W2 size construction failed: %s (sum=%d)" % (sizes[:8], sum(sizes)))
    sigma_table = [args.sigma_tight, args.sigma_mid, args.sigma_loose]
    kind_table = ["tight", "mid", "loose"]
    # heavy classes loose, light classes tight (anti-correlated with size)
    kinds = []
    for i in range(classes):
        frac = i / max(1, classes - 1)
        kinds.append(2 if frac < 1.0 / 3 else (1 if frac < 2.0 / 3 else 0))
    centers = [f32round([rng.uniform(-args.box, args.box) for _ in range(args.d)])
              for _ in range(classes)]
    eps = math.sqrt(args.radius) if args.radius else 1.0  # boundary placement needs epsilon
    if not args.radius:
        raise SystemExit("W2 requires --radius (epsilon anchors boundary vectors)")
    vecs, labels = [], []
    anchors_by_class = {c: [] for c in range(classes)}
    boundary_table = []
    t_grid = [0.90, 0.93, 0.96, 0.99, 1.00, 1.01, 1.04, 1.07, 1.10]
    idx = 0
    for c in range(classes):
        sigma = sigma_table[kinds[c]]
        for _ in range(sizes[c]):
            if anchors_by_class[c] and rng.random() < args.boundary_frac:
                anchor_pos = rng.randrange(len(anchors_by_class[c]))
                anchor_id, anchor = anchors_by_class[c][anchor_pos]
                u = [rng.gauss(0.0, 1.0) for _ in range(args.d)]
                norm = math.sqrt(sum(t * t for t in u)) or 1.0
                u = [t / norm for t in u]
                t = rng.choice(t_grid)
                x = f32round([a + t * eps * uu for a, uu in zip(anchor, u)])
                actual = sq_l2(anchor, x)
                boundary_table.append({
                    "id": idx, "anchor": anchor_id, "class": c, "t": t,
                    "actual_sq_dist": actual,
                    "inside_strict_lt": bool(actual < args.radius),
                })
            else:
                ctr = centers[c]
                x = f32round([z + rng.gauss(0.0, sigma) for z in ctr])
            vecs.append(x)
            labels.append(c)
            anchors_by_class[c].append((idx, x))
            idx += 1
    meta_extra = {
        "centers": centers,
        "class_sizes": sizes,
        "class_sigmas": [sigma_table[k] for k in kinds],
        "class_kinds": [kind_table[k] for k in kinds],
        "boundary_count": len(boundary_table),
        "boundary_table": boundary_table,
    }
    return vecs, labels, meta_extra


def distance_stats(vecs, labels, rng, within_cap=150, cross_samples=20000):
    n = len(vecs)
    by_class = {}
    for i, lab in enumerate(labels):
        by_class.setdefault(lab, []).append(i)
    within = []
    for lab, ids in by_class.items():
        m = len(ids)
        if m < 2:
            continue
        k = min(within_cap, m * (m - 1) // 2)
        for _ in range(k):
            a, b = rng.sample(ids, 2)
            within.append(sq_l2(vecs[a], vecs[b]))
    cross = []
    labs = list(by_class)
    tries = 0
    while len(cross) < cross_samples and tries < cross_samples * 10:
        a = rng.randrange(n)
        b = rng.randrange(n)
        tries += 1
        if labels[a] != labels[b]:
            cross.append(sq_l2(vecs[a], vecs[b]))
    return {
        "within_class_pairs_sampled": len(within),
        "within_class_sq_l2": quantiles(within),
        "cross_class_pairs_sampled": len(cross),
        "cross_class_sq_l2": quantiles(cross),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["W1", "W2"], required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--d", type=int, default=16)
    ap.add_argument("--classes", type=int, default=40)
    ap.add_argument("--cluster-num", type=int, default=120)
    ap.add_argument("--K", type=int, default=24)
    ap.add_argument("--box", type=float, default=0.15)
    ap.add_argument("--sigma", type=float, default=0.08)
    ap.add_argument("--sigma-tight", type=float, default=0.03)
    ap.add_argument("--sigma-mid", type=float, default=0.08)
    ap.add_argument("--sigma-loose", type=float, default=0.13)
    ap.add_argument("--boundary-frac", type=float, default=0.20)
    ap.add_argument("--radius", type=float, default=0.0,
                    help="squared-L2 threshold; 0 = stats only (no config)")
    ap.add_argument("--mem-budget", type=float, default=0.1)
    ap.add_argument("--error-bound", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=283)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data"))
    args = ap.parse_args()

    if args.n < 1000 or args.n % 1000:
        raise SystemExit("n must be >=1000 and divisible by 1000")
    if args.d % 8:
        raise SystemExit("d must be divisible by 8 (AVX2 path)")
    if not (0.0 < args.mem_budget <= 1.0):
        raise SystemExit("mem_budget must be in (0, 1] GiB")
    if not (0.0 < args.error_bound <= 1.0):
        raise SystemExit("error_bound in paper-legal range (0, 1]")

    rng = random.Random(args.seed)
    if args.mode == "W1":
        vecs, labels, extra = gen_W1(args, rng)
    else:
        vecs, labels, extra = gen_W2(args, rng)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fbin = out / ("%s.fbin" % args.name)

    # write fbin (content identical across invocations with same seed)
    with fbin.open("wb") as f:
        f.write(struct.pack("<II", args.n, args.d))
        for x in vecs:
            f.write(struct.pack("<%df" % args.d, *x))

    stats = distance_stats(vecs, labels, random.Random(args.seed + 1))

    id0 = 0
    if args.radius:
        v0 = vecs[0]
        id0 = sum(1 for j in range(1, args.n) if sq_l2(v0, vecs[j]) < args.radius)
        if id0 == 0:
            raise SystemExit("ID-0 neighbourhood empty; config.gt would be 0 (div-by-zero). "
                              "Adjust radius/seed; do NOT tune on holdout results.")
        cfg = out / ("%s.config" % args.name)
        lines = {
            "data_file": fbin,
            "radius": format(args.radius, ".9g"),
            "cluster_num": args.cluster_num,
            "cluster_file": out / ("%s.clusters" % args.name),
            "metadata_file": out / ("%s.metadata" % args.name),
            "hnsw_file": out / ("%s.hnsw" % args.name),
            "K": args.K,
            "mem_budget": args.mem_budget,
            "error_bound": args.error_bound,
            "gt": id0,
        }
        cfg.write_text("".join("%-16s %s\n" % (k, v) for k, v in lines.items()),
                       encoding="utf-8")

    meta = {
        "mode": args.mode, "name": args.name, "seed": args.seed,
        "n": args.n, "d": args.d, "classes": args.classes,
        "cluster_num": args.cluster_num, "K": args.K,
        "box": args.box, "sigma": args.sigma,
        "sigma_tight": args.sigma_tight, "sigma_mid": args.sigma_mid,
        "sigma_loose": args.sigma_loose, "boundary_frac": args.boundary_frac,
        "radius": args.radius, "epsilon": math.sqrt(args.radius) if args.radius else None,
        "mem_budget": args.mem_budget, "error_bound": args.error_bound,
        "id0_neighbours": id0,
        "distance_stats": stats,
        "class_sizes_actual": {str(c): labels.count(c) for c in sorted(set(labels))},
    }
    meta.update(extra)
    (out / ("%s_meta.json" % args.name)).write_text(json.dumps(meta, indent=1),
                                                     encoding="utf-8")
    print(json.dumps({"fbin": str(fbin), "n": args.n, "d": args.d, "mode": args.mode,
                      "id0_neighbours": id0, "stats": stats}, indent=1))


if __name__ == "__main__":
    main()
