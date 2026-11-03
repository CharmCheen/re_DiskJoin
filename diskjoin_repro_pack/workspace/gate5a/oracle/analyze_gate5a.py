#!/usr/bin/env python3
"""Gate 5A analysis: BigANN100K real-data pilot.

Read-only analysis over workspace/gate5a/{runs,logs,data}. Pure stdlib.

  1. Per-run parsing of instrumentation stderr/stdout + trace/tasks/pairs.
  2. Sampled exact-GT recall over the 201 pre-registered endpoints
     (200 uniform random.Random(20260101) + explicit vector 0):
       - endpoint-level recall (pairs counted at BOTH endpoints when both
         sampled - pre-registered double-count rule) + Wilson 95% CI on the
         pooled ratio, per-endpoint distribution;
       - pair-level (deduplicated) recall variant;
       - FP check: found pairs not in exact GT (expect 0 - threshold is
         exact integer arithmetic on both sides);
       - cross-check vs in-binary sampled recall (id%100000==0 -> vector 0)
         and config gt=3 == |N(0)| from the GT file.
  3. Pair-set identity across order x policy runs (r1-r4) and knn.txt
     (candidate graph) invariance; r6 (ASan+prefetch-guard) byte-identity
     vs r1; v0 synthetic regression vs gate4b1 frozen run.
  4. Cache mechanism verification: lockstep trace replay of the C++
     belady_reject / belady_forced / lru_forced semantics, read_calls ==
     miss, O_DIRECT effective/requested byte recomputation from metadata,
     LRU stack-distance accounting (miss_D == cold + #{sd >= cap}).
  5. Locality digest of the Gorder access sequence.
Outputs: results/*.tsv + markdown digest on stdout.
"""
import re
import sys
import math
import struct
import hashlib
from pathlib import Path
from collections import defaultdict

WS = Path("/home/qch/DiskJoin/diskjoin_repro_pack/workspace")
G5A = WS / "gate5a"
RUNS = G5A / "runs"
LOGS = G5A / "logs"
DATA = G5A / "data"
RES = G5A / "results"
PAGE = 4096
D = 128

SENTINEL = None  # SIZE_MAX (never used again)

REAL_RUNS = ["r1_default", "r2_identity", "r3_gorder_lru_forced",
             "r4_gorder_belady_forced", "r5_default_asan",
             "r6_default_asan_patched", "v0"]


# ---------------------------------------------------------------- parsing

def parse_kv_line(line):
    out = {}
    for tok in line.strip().split("]", 1)[1].split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def parse_stderr(name):
    d = {}
    text = (LOGS / f"{name}.stderr").read_text(errors="replace")
    for line in text.splitlines():
        for tag in ("gate4a-config", "gate4a-cache", "gate4b1-io", "gate3-stat",
                    "gate3-inv", "gate4a-gorder", "gate4b0", "gate4a-writer",
                    "gate4b1"):
            if line.startswith(f"[{tag}]"):
                d[tag] = parse_kv_line(line)
    return d


def parse_stdout(name):
    text = (LOGS / f"{name}.stdout").read_text(errors="replace")
    b = re.search(r"\[([\d.]+) s\] Build done", text)
    j = re.search(r"\[([\d.]+) s\] Join done", text)
    rc = re.search(r"recall = ([\d.eE+-]+|nan)", text)
    build = float(b.group(1)) if b else None
    join = float(j.group(1)) if j else None
    search = (join - build) if (b and j) else None
    return {"build_s": build, "join_cum_s": join, "search_s": search,
            "printed_recall": rc.group(1) if rc else None}


def parse_trace(path):
    acc, push = [], []
    miss_ids = []
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "A":
                acc.append((int(p[1]), int(p[2]), int(p[3])))
                if int(p[3]) == 0:
                    miss_ids.append(int(p[2]))
            elif p[0] == "P":
                push.append((int(p[1]), int(p[2]), p[3], int(p[4])))
    return acc, push, miss_ids


def parse_tasks(path):
    lists = {}
    targets = {}
    with open(path) as f:
        for line in f:
            p = [int(x) for x in line.split()]
            lists[p[0]] = p[3:3 + p[2]]
            targets[p[0]] = p[1]
    seq = []
    for slot in sorted(lists):
        seq.extend(lists[slot])
    return seq, [targets[s] for s in sorted(lists)], [lists[s] for s in sorted(lists)]


def load_gt_endpoints(path):
    gt = {}
    zero_line = None
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            p = [int(x) for x in line.split()]
            e, k, ids = p[0], p[1], p[2:]
            assert len(ids) == k
            gt[e] = ids
            if e == 0:
                zero_line = (k, ids)
    return gt, zero_line


def wilson_ci(k, n, z=1.959963985):
    if n == 0:
        return None, None
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


# ---------------------------------------------------------------- models

def next_use_table(seq):
    nxt = [SENTINEL] * len(seq)
    last = {}
    for i in range(len(seq) - 1, -1, -1):
        nxt[i] = last.get(seq[i], SENTINEL)
        last[seq[i]] = i
    return nxt


def vickey(nu, v):
    return (2, 0, -v) if nu is SENTINEL else (1, nu, -v)


def lockstep(seq, cap, trace_acc, trace_push, policy):
    """Simulate policy on seq lockstep against the trace. Policies:
       C belady_reject (reference), A belady_forced, D lru_forced."""
    nxt = next_use_table(seq)
    iters = defaultdict(list)
    for pos, x in enumerate(seq):
        iters[x].append(pos)
    ptr = defaultdict(int)
    for x in iters:
        iters[x].append(SENTINEL)
    res = {}
    total = hit = miss = admit = evict = reject = 0
    m_A = m_type = m_victim = m_victim_equiv = 0
    push_it = iter(trace_push)
    for i, x in enumerate(seq):
        ptr[x] += 1
        nu = iters[x][ptr[x]]
        total += 1
        tr = trace_acc[i]
        if tr[0] != total or tr[1] != x:
            return None
        if x in res:
            hit += 1
            if policy == "D":
                res[x] = i
            else:
                res[x] = nu
            if tr[2] != 1:
                m_A += 1
        else:
            miss += 1
            if tr[2] != 0:
                m_A += 1
            tp = next(push_it)
            if tp[0] != total or tp[1] != x:
                return None
            if len(res) < cap:
                res[x] = i if policy == "D" else nu
                admit += 1
                if tp[2] != "admit":
                    m_type += 1
            elif policy == "C":
                vfar = max(res, key=lambda v: vickey(res[v], v))
                vfar_nu = res[vfar]
                better = (nu is not SENTINEL and vfar_nu is SENTINEL) or \
                         (nu is not SENTINEL and vfar_nu is not SENTINEL and vfar_nu > nu)
                if better:
                    del res[vfar]
                    res[x] = nu
                    evict += 1
                    if tp[2] != "evict":
                        m_type += 1
                    elif tp[3] != vfar:
                        # tie-break difference among equal keys: non-sentinel
                        # next-use keys are unique per position, so a differing
                        # victim with identical counters can only be a
                        # never-used-again (SIZE_MAX key) tie -> functionally
                        # equivalent eviction.
                        tr_v = tp[3]
                        nu_tr = iters[tr_v][ptr[tr_v]] if ptr[tr_v] < len(iters[tr_v]) else SENTINEL
                        nu_mod = iters[vfar][ptr[vfar]] if ptr[vfar] < len(iters[vfar]) else SENTINEL
                        if nu_tr is SENTINEL and nu_mod is SENTINEL:
                            m_victim_equiv += 1
                        else:
                            m_victim += 1
                else:
                    reject += 1
                    if tp[2] != "reject":
                        m_type += 1
            else:
                if policy == "A":
                    victim = max(res, key=lambda v: vickey(res[v], v))
                else:
                    victim = min(res, key=lambda v: res[v])
                del res[victim]
                res[x] = i if policy == "D" else nu
                evict += 1
                if tp[2] != "evict":
                    m_type += 1
                elif tp[3] != victim:
                    tr_v = tp[3]
                    nu_tr = iters[tr_v][ptr[tr_v]] if ptr[tr_v] < len(iters[tr_v]) else SENTINEL
                    nu_mod = iters[victim][ptr[victim]] if ptr[victim] < len(iters[victim]) else SENTINEL
                    if nu_tr is SENTINEL and nu_mod is SENTINEL:
                        m_victim_equiv += 1
                    else:
                        m_victim += 1
    return {"total": total, "hit": hit, "miss": miss, "admit": admit,
            "evict": evict, "reject": reject, "A_mismatch": m_A,
            "type_mismatch": m_type, "victim_mismatch": m_victim,
            "victim_equiv": m_victim_equiv}


def stack_distances(seq):
    last = {}
    order = []
    pos_of = {}
    dists = []
    for i, x in enumerate(seq):
        if x in last:
            d = len(order) - 1 - pos_of[x]
            dists.append(d)
            order.pop(pos_of[x])
            for k in range(pos_of[x], len(order)):
                pos_of[order[k]] = k
        else:
            dists.append(None)
        order.append(x)
        pos_of[x] = len(order) - 1
        last[x] = i
    return dists


# ---------------------------------------------------------------- metadata

def load_metadata(path):
    with open(path, "rb") as f:
        n, d, cn, mp = struct.unpack("<4Q", f.read(32))
        sizes = struct.unpack(f"<{cn}Q", f.read(8 * cn))
    file_pos = []
    cumu = 0
    for s in sizes:
        file_pos.append(cumu * d * 4)
        cumu += s
    return n, d, cn, mp, sizes, file_pos


def div_round_up(a, b):
    return (a + b - 1) // b


# ---------------------------------------------------------------- main

def main():
    RES.mkdir(exist_ok=True)
    problems = []

    # ---- load GT
    gt, zero_gt = load_gt_endpoints(DATA / "gt_m272.txt")
    E = set(gt.keys())
    gt_sets = {e: set(ids) for e, ids in gt.items()}
    n_gt0 = sum(1 for e in E if len(gt_sets[e]) == 0)
    total_gt_pairs_endpoint_level = sum(len(v) for v in gt_sets.values())
    gt_pair_set = set()
    for e, ids in gt.items():
        for j in ids:
            gt_pair_set.add((min(e, j), max(e, j)))

    print("## Ground truth (exact integer brute force, m=272, thr=73984)")
    print(f"- endpoints: {len(E)} (200 sampled + vector 0); |N(0)|={zero_gt[0]} (config gt)")
    print(f"- endpoints with empty neighbourhood (excluded from recall ratios): {n_gt0}")
    print(f"- endpoint-level GT pair incidences: {total_gt_pairs_endpoint_level}")
    print(f"- deduplicated GT pairs touching E: {len(gt_pair_set)}")

    # ---- per-run stats
    print("\n## Runs")
    rows = {}
    for name in REAL_RUNS:
        stderr_f = LOGS / f"{name}.stderr"
        if not stderr_f.exists():
            print(f"- {name}: NO LOG")
            continue
        s = parse_stderr(name)
        o = parse_stdout(name)
        rows[name] = {**s, **o}
        rc_line = ""
        if name == "r5_default_asan":
            text = stderr_f.read_text(errors="replace")
            m = re.search(r"ERROR: AddressSanitizer: (\S+)", text)
            f = re.search(r"in (\S+\(\)\s*\S*)", text)
            rc_line = f" | ASAN ABORT: {m.group(1) if m else '?'} in hnswlib searchBaseLayer (build phase)"
        print(f"- {name}: build={o['build_s']}s search={o['search_s']}s "
              f"recall={o['printed_recall']}"
              f" | task_total={s.get('gate3-inv', {}).get('task_total')} "
              f"hit={s.get('gate4a-cache', {}).get('hit')} "
              f"miss={s.get('gate4a-cache', {}).get('miss')}"
              f" evict={s.get('gate4a-cache', {}).get('evict')}"
              f" reject={s.get('gate4a-cache', {}).get('reject')}"
              f" | dist_comp={s.get('gate3-stat', {}).get('dist_comp')}"
              f"{rc_line}")

    # ---- recall (r1; pair-set identity extends it to r2-r4)
    print("\n## Sampled recall (r1_default; exact GT, strict <)")
    found = defaultdict(set)      # endpoint -> partners found
    n_pairs_total = 0
    dup_pairs = 0
    seen_pairs = set()
    with open(RUNS / "r1_default" / "pairs.txt") as f:
        for line in f:
            a, b = line.split()
            a, b = int(a), int(b)
            n_pairs_total += 1
            pk = (a, b)
            if pk in seen_pairs:
                dup_pairs += 1
            else:
                seen_pairs.add(pk)
            if a in E:
                found[a].add(b)
            if b in E:
                found[b].add(a)
    print(f"- pairs dumped: {n_pairs_total} (distinct {len(seen_pairs)}, duplicated lines {dup_pairs})")

    # endpoint-level (double-count rule)
    k_sum = n_sum = 0
    recs = []
    bad_gt0 = 0
    fp_incidents = 0
    for e in sorted(E):
        gt_e = gt_sets[e]
        if not gt_e:
            bad_gt0 += 1
            continue
        f_e = found[e]
        tp = len(f_e & gt_e)
        fp = len(f_e - gt_e)
        fp_incidents += fp
        recs.append(tp / len(gt_e))
        k_sum += tp
        n_sum += len(gt_e)
    recs_sorted = sorted(recs)
    lo, hi = wilson_ci(k_sum, n_sum)
    print(f"- endpoint-level pooled recall: {k_sum}/{n_sum} = {k_sum/n_sum:.6f}"
          f"  Wilson95% [{lo:.6f}, {hi:.6f}]")
    print(f"- per-endpoint recall over {len(recs)} endpoints with GT>0: "
          f"min={recs_sorted[0]:.4f} median={recs_sorted[len(recs_sorted)//2]:.4f} "
          f"mean={sum(recs)/len(recs):.4f} max={recs_sorted[-1]:.4f}")
    print(f"- endpoints with recall==0: {sum(1 for r in recs if r == 0.0)}; ==1: {sum(1 for r in recs if r == 1.0)}")
    print(f"- false-positive pair incidences (found partner not in exact GT): {fp_incidents} (expect 0)")

    # pair-level dedup
    found_pair_set = set()
    for e, partners in found.items():
        for j in partners:
            found_pair_set.add((min(e, j), max(e, j)))
    tp_p = len(found_pair_set & gt_pair_set)
    fp_p = len(found_pair_set - gt_pair_set)
    lo_p, hi_p = wilson_ci(tp_p, len(gt_pair_set))
    print(f"- pair-level (dedup) recall: {tp_p}/{len(gt_pair_set)} = {tp_p/len(gt_pair_set):.6f}"
          f"  Wilson95% [{lo_p:.6f}, {hi_p:.6f}]  FP pairs: {fp_p}")

    # in-binary cross-check
    f0 = found[0]
    print(f"- vector 0: GT={sorted(gt_sets[0])} found={sorted(f0)} -> in-binary count={len(f0)} "
          f"(stderr sampled_count={rows['r1_default'].get('gate3-stat', {}).get('sampled_count')}, "
          f"config gt={zero_gt[0]}, printed recall={rows['r1_default']['printed_recall']})")
    if len(f0) != rows["r1_default"]["gate3-stat"]["sampled_count"]:
        problems.append("sampled_count != pairs involving vector 0")

    # ---- knn/pair identity across r1-r4
    print("\n## Cross-run invariance (r1..r4)")
    for name in REAL_RUNS[1:4]:
        a = (RUNS / "r1_default" / "knn.txt").read_bytes()
        b = (RUNS / name / "knn.txt").read_bytes()
        print(f"- knn.txt r1 vs {name}: {'IDENTICAL' if a == b else 'DIFFERS'}")
        if a != b:
            problems.append(f"knn.txt differs r1 vs {name}")
    base = seen_pairs
    for name in REAL_RUNS[1:4]:
        path = RUNS / name / "pairs.txt"
        cnt = 0
        miss = 0
        with open(path) as f:
            for line in f:
                a, b = line.split()
                pk = (int(a), int(b))
                cnt += 1
                if pk not in base:
                    miss += 1
        st = "IDENTICAL" if (cnt == n_pairs_total and miss == 0) else "DIFFERS"
        print(f"- pairs.txt r1 vs {name}: {st} (lines={cnt}, not-in-r1={miss})")
        if st == "DIFFERS":
            problems.append(f"pair set differs r1 vs {name}")

    # r6 byte-identity
    for f_ in ("knn.txt", "tasks.txt", "pairs.txt", "trace.txt"):
        a = (RUNS / "r1_default" / f_).read_bytes()
        b = (RUNS / "r6_default_asan_patched" / f_).read_bytes()
        if a != b:
            problems.append(f"r6 differs from r1 on {f_}")
    print(f"- r6 (ASan + prefetch guard) vs r1: knn/tasks/pairs/trace byte-identity: "
          f"{'ALL IDENTICAL' if not any('r6 differs' in p for p in problems) else 'DIFFERS'}")

    # v0 vs gate4b1 frozen
    v0ok = True
    for f_ in ("knn.txt", "tasks.txt", "pairs.txt", "trace.txt"):
        a = (RUNS / "v0" / f_).read_bytes()
        b = (WS / "gate4b1" / "runs" / "p1_default" / f_).read_bytes()
        if a != b:
            v0ok = False
            problems.append(f"v0 differs from gate4b1 p1_default on {f_}")
    print(f"- v0 (synthetic p1, gate5a binary) vs gate4b1 frozen p1_default: "
          f"{'ALL 4 DUMPS BYTE-IDENTICAL' if v0ok else 'DIFFERS'}")

    # ---- cache mechanism verification
    print("\n## Cache mechanism verification (lockstep trace replay)")
    for name, pol in (("r1_default", "C"), ("r2_identity", "C"),
                      ("r3_gorder_lru_forced", "D"), ("r4_gorder_belady_forced", "A")):
        acc, push, miss_ids = parse_trace(RUNS / name / "trace.txt")
        seq, targets, slot_lists = parse_tasks(RUNS / name / "tasks.txt")
        cap = rows[name]["gate4a-cache"]["capacity_slots"]
        r = lockstep(seq, cap, acc, push, pol)
        cstat = rows[name]["gate4a-cache"]
        ok = (r and r["hit"] == cstat["hit"] and r["miss"] == cstat["miss"]
              and r["admit"] == cstat["admit"] and r["evict"] == cstat["evict"]
              and r["reject"] == cstat["reject"] and r["A_mismatch"] == 0
              and r["type_mismatch"] == 0 and r["victim_mismatch"] == 0)
        print(f"- {name} policy={pol}: replay {'MATCHES' if ok else 'MISMATCH'} "
              f"(hit={r['hit']}/{cstat['hit']} miss={r['miss']}/{cstat['miss']} "
              f"admit={r['admit']}/{cstat['admit']} evict={r['evict']}/{cstat['evict']} "
              f"reject={r['reject']}/{cstat['reject']} "
              f"acc_mis={r['A_mismatch']} type_mis={r['type_mismatch']} "
              f"victim_mis={r['victim_mismatch']} victim_equiv={r['victim_equiv']})")
        if not ok:
            problems.append(f"lockstep mismatch {name}")
        if rows[name]["gate4b1-io"]["read_calls"] != cstat["miss"]:
            problems.append(f"read_calls != miss in {name}")
    print(f"- read_calls == miss for r1-r4: "
          f"{'OK' if not any('read_calls' in p for p in problems) else 'VIOLATION'}")

    # ---- IO recompute (r1)
    n_, d_, cn_, mp_, sizes, file_pos = load_metadata(DATA / "frozen_r1" / "bigann100k.metadata")
    acc, push, miss_ids = parse_trace(RUNS / "r1_default" / "trace.txt")
    eff = sum(sizes[b] * d_ * 4 for b in miss_ids)
    req = sum(div_round_up(file_pos[b] % PAGE + sizes[b] * d_ * 4, PAGE) * PAGE for b in miss_ids)
    io = rows["r1_default"]["gate4b1-io"]
    print(f"\n## O_DIRECT IO recompute (r1): effective {eff} vs {io['effective_bytes']}; "
          f"requested {req} vs {io['requested_aligned_bytes']}")
    if eff != io["effective_bytes"] or req != io["requested_aligned_bytes"]:
        problems.append("IO byte recompute mismatch")

    # ---- LRU stack-distance accounting (r1 sequence, policy-D semantics)
    seq, targets, slot_lists = parse_tasks(RUNS / "r1_default" / "tasks.txt")
    cap = rows["r1_default"]["gate4a-cache"]["capacity_slots"]
    dists = stack_distances(seq)
    finite = [x for x in dists if x is not None]
    cold = len(seq) - len(finite)
    sd_ge_cap = sum(1 for x in finite if x >= cap)
    r3_miss = rows["r3_gorder_lru_forced"]["gate4a-cache"]["miss"]
    print(f"\n## LRU accounting (r1 access sequence, cap={cap})")
    print(f"- accesses={len(seq)} distinct={len(set(seq))} cold(first)={cold} "
          f"repeat={len(finite)} sd>=cap={sd_ge_cap}")
    print(f"- cold + #(sd>=cap) = {cold + sd_ge_cap} vs r3 lru_forced miss = {r3_miss} "
          f"({'MATCH' if cold + sd_ge_cap == r3_miss else 'MISMATCH'})")
    if cold + sd_ge_cap != r3_miss:
        problems.append("LRU stack accounting mismatch")

    # ---- locality digest (r1 = gorder)
    inter = [len(set(slot_lists[i]) & set(slot_lists[i + 1]))
             for i in range(len(slot_lists) - 1)]
    print(f"- gorder sequence: interslot overlap mean={sum(inter)/len(inter):.3f}; "
          f"sd_median={sorted(finite)[len(finite)//2]} sd_mean={sum(finite)/len(finite):.1f}")

    # ---- task graph digest
    inv = rows["r1_default"]["gate3-inv"]
    gorder = rows["r1_default"].get("gate4a-gorder", {})
    print(f"\n## Task graph (r1): task_total={inv['task_total']} "
          f"upper_triangle_ok={inv['upper_triangle_ok']} perm_ok={inv['perm_ok']} "
          f"empty_tasks={inv['empty_tasks']} bucket_sum={inv['bucket_sum']} "
          f"| gorder: window={gorder.get('window')} insertions={gorder.get('insertions')} "
          f"window_removals={gorder.get('window_removals')} perm_ok={gorder.get('perm_ok')}")

    # ---- verdict inputs
    print("\n## Problems")
    if problems:
        for p in problems:
            print(f"- {p}")
    else:
        print("- none")

    # ---- results files
    with open(RES / "runs_summary.tsv", "w") as f:
        f.write("run\tbuild_s\tsearch_s\tprinted_recall\ttask_total\thit\tmiss\tevict\treject\tread_calls\tdist_comp\n")
        for name in REAL_RUNS:
            r = rows.get(name)
            if not r:
                continue
            c = r.get("gate4a-cache", {})
            io = r.get("gate4b1-io", {})
            st = r.get("gate3-stat", {})
            inv = r.get("gate3-inv", {})
            f.write(f"{name}\t{r.get('build_s')}\t{r.get('search_s')}\t{r.get('printed_recall')}\t"
                    f"{inv.get('task_total')}\t{c.get('hit')}\t{c.get('miss')}\t{c.get('evict')}\t{c.get('reject')}\t"
                    f"{io.get('read_calls')}\t{st.get('dist_comp')}\n")
    with open(RES / "recall_summary.tsv", "w") as f:
        f.write("metric\tk\tn\trate\twilson_lo\twilson_hi\n")
        f.write(f"endpoint_level\t{k_sum}\t{n_sum}\t{k_sum/n_sum:.6f}\t{lo:.6f}\t{hi:.6f}\n")
        f.write(f"pair_level\t{tp_p}\t{len(gt_pair_set)}\t{tp_p/len(gt_pair_set):.6f}\t{lo_p:.6f}\t{hi_p:.6f}\n")
    print(f"\nresults written to {RES}/runs_summary.tsv, recall_summary.tsv")


if __name__ == "__main__":
    main()
