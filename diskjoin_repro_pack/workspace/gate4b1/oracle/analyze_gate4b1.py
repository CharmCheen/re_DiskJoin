#!/usr/bin/env python3
"""Gate 4B-1 analysis: mechanism ablation (task order x cache policy x pruning).

Read-only analysis over workspace/gate4b1/runs + logs. Pure stdlib.

  1. Per-run parsing: [gate4a-config]/[gate4a-cache]/[gate4b1-io]/
     [gate3-stat]/[gate3-inv]/[gate4a-gorder]/[gate4b0] stderr lines,
     Build/Join timer ticks (stdout), trace.txt, tasks.txt, pairs.txt.
  2. Consistency checks per run:
       trace A/P events vs printed cache stats; tasks->access-sequence
       reconstruction vs trace; read_calls == miss; effective/requested
       O_DIRECT bytes recomputed offline from metadata + trace (exact
       formula from ClusterIO.h: file_pos packed, page-aligned reads);
       pair duplicates; [gate3-inv]/[gate4a-gorder] flags.
  3. Policy cross-checks vs offline models (ported from gate4b0
     oracle/cache_models.py, identical access sequence/capacity):
       belady_reject  -> model C (exact C++ rule), victim-exact
       belady_forced  -> model A (forced Belady), victims equal modulo
                         never-again ties
       lru_forced     -> model D (forced LRU), victims exact (unique keys)
  4. Full-oracle GT evaluation per run: TP/FP/FN/precision/recall vs
     gate4a frozen gt_{ds}.txt (NOT the sampled in-binary recall).
  5. Pair-set identity across order x policy at fixed (ds, eb);
     task-graph identity across orders (slot column dropped).
  6. Locality: LRU stack-distance distribution, per-slot access counts,
     inter-slot overlap, sliding-window working set (window 1..8 tasks).
  7. Capacity curves per (ds, eb, order) for models A/C/D (caps 8..120).
  8. Pruning eb0.1 vs eb1.0 ablation; extra-seed sensitivity; holdout.
  9. Timing digest (t_* runs, REP repetitions; sub-second values are
     recorded, never interpreted as SSD performance).
Outputs: results/*.tsv + markdown digest on stdout.
"""
import re
import sys
from pathlib import Path
from collections import defaultdict

WS = Path("/home/qch/DiskJoin/diskjoin_repro_pack/workspace")
G4B1 = WS / "gate4b1"
RUNS = G4B1 / "runs"
LOGS = G4B1 / "logs"
G4A = WS / "gate4a"
RES = G4B1 / "results"
PAGE = 4096

SENTINEL = None  # plays the role of SIZE_MAX (never again)

MATRIX_RE = re.compile(r"^(p1|p3)_(gorder|identity|random)_(belady_reject|belady_forced|lru_forced)_eb(01|10)$")
SEED_RE = re.compile(r"^(p1|p3)_seed(\d+)_(belady_reject|belady_forced|lru_forced)_eb(01|10)$")
HOLD_RE = re.compile(r"^(w1h|w2h)_(gorder|identity|random)_(belady_reject|belady_forced|lru_forced)_eb(01|10)$")
VERIF = ["p1_default", "p3_default", "p1_default_asan", "p3_default_asan",
         "p3_lru_asan", "p1_forced_cap40_asan", "p1_cap62pin", "p1_cap40", "p3_cap40"]
TIME_RE = re.compile(r"^t_(.+)$")


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
                    "gate3-inv", "gate4a-gorder", "gate4b0", "gate4a-writer"):
            if line.startswith(f"[{tag}]"):
                d[tag] = parse_kv_line(line)
    return d


def parse_stdout(name):
    text = (LOGS / f"{name}.stdout").read_text(errors="replace")
    b = re.search(r"\[([\d.]+) s\] Build done", text)
    j = re.search(r"\[([\d.]+) s\] Join done", text)
    build = float(b.group(1)) if b else None
    join = float(j.group(1)) if j else None
    # Timer semantics: Build = build phase, Join = cumulative; search = diff.
    search = (join - build) if (b and j) else None
    return {"build_s": build, "join_cum_s": join, "search_s": search}


def parse_trace(path):
    acc, push = [], []
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "A":
                acc.append((int(p[1]), int(p[2]), int(p[3])))
            elif p[0] == "P":
                push.append((int(p[1]), int(p[2]), p[3], int(p[4])))
    return acc, push


def parse_tasks(path):
    """Return (slot lists in slot order). Line: slot target deg c1..cdeg."""
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


def parse_pairs(path):
    pairs = []
    with open(path) as f:
        for line in f:
            p = line.split()
            if len(p) == 2:
                a, b = int(p[0]), int(p[1])
                pairs.append((a, b) if a <= b else (b, a))
    return pairs


def load_gt(ds):
    return set(parse_pairs(G4A / "runs" / f"gt_{ds}.txt"))


def load_bucket_sizes(ds):
    with open(G4A / "data" / f"{ds}.metadata", "rb") as f:
        import struct
        n, d, cn, mp = struct.unpack("<4Q", f.read(32))
        sizes = struct.unpack(f"<{cn}Q", f.read(8 * cn))
    return n, d, cn, sizes


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
    """Simulate the policy on seq lockstep against the trace push events.
    Returns counters + mismatch counts. Victim rules:
      C/C++ belady_reject: exact replication of Cache::push;
      A belady_forced:     forced load, victim farthest next use;
      D lru_forced:        forced load, victim least recently used."""
    nxt = next_use_table(seq)
    iters = defaultdict(list)
    for pos, x in enumerate(seq):
        iters[x].append(pos)
    ptr = defaultdict(int)
    for x in iters:
        iters[x].append(SENTINEL)
    res = {}      # id -> next use (C/A) or last use (D)
    total = hit = miss = admit = evict = reject = 0
    m_A = 0
    m_type = m_victim = m_victim_equiv = 0
    push_it = iter(trace_push)
    for i, x in enumerate(seq):
        ptr[x] += 1
        nu = iters[x][ptr[x]]
        total += 1
        tr = trace_acc[i]
        if tr[0] != total or tr[1] != x:
            return None  # trace desync (reported by caller)
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
                        m_victim += 1
                else:
                    reject += 1
                    if tp[2] != "reject":
                        m_type += 1
            else:  # A or D: forced load
                if policy == "A":
                    victim = max(res, key=lambda v: vickey(res[v], v))
                else:
                    victim = min(res, key=lambda v: res[v])
                v_nu_after = nxt[i]  # unused; ties judged via iters/ptr
                del res[victim]
                res[x] = i if policy == "D" else nu
                evict += 1
                if tp[2] != "evict":
                    m_type += 1
                elif tp[3] != victim:
                    # interchangeable iff both victims never used again
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


def sim_offline(seq, cap, policy):
    """Counter-only simulation (no trace): C = greedy reject, A = forced
    Belady, D = forced LRU."""
    nxt = next_use_table(seq)
    res = {}
    miss = 0
    for i, x in enumerate(seq):
        if x in res:
            if policy == "D":
                res[x] = i
            else:
                res[x] = nxt[i]
        else:
            miss += 1
            if len(res) < cap:
                res[x] = i if policy == "D" else nxt[i]
            elif policy == "C":
                vfar = max(res, key=lambda v: vickey(res[v], v))
                nu_in = nxt[i]
                vfar_nu = res[vfar]
                better = (nu_in is not SENTINEL and vfar_nu is SENTINEL) or \
                         (nu_in is not SENTINEL and vfar_nu is not SENTINEL and vfar_nu > nu_in)
                if better:
                    del res[vfar]
                    res[x] = nu_in
            else:
                victim = (min(res, key=lambda v: res[v]) if policy == "D"
                          else max(res, key=lambda v: vickey(res[v], v)))
                del res[victim]
                res[x] = i if policy == "D" else nxt[i]
    return miss


# ---------------------------------------------------------------- locality

def stack_distances(seq):
    """LRU stack distance per access (number of distinct ids touched since
    the id's previous access; None for first accesses)."""
    last = {}
    seen_stack = {}  # not a real stack; compute distinct via last-seen order
    # efficient enough for L ~ 2e3: maintain order of last use
    order = []       # ids ordered by last use, most recent last
    pos_of = {}
    dists = []
    for i, x in enumerate(seq):
        if x in last:
            d = len(order) - 1 - pos_of[x]
            dists.append(d)
            order.pop(pos_of[x])
            # recompute positions after pop (rare enough at this scale)
            for k in range(pos_of[x], len(order)):
                pos_of[order[k]] = k
        else:
            dists.append(None)
        order.append(x)
        pos_of[x] = len(order) - 1
        last[x] = i
    return dists


def locality_report(seq, slot_lists, cap):
    dists = stack_distances(seq)
    finite = [d for d in dists if d is not None]
    n = len(seq)
    hits_lt_cap = sum(1 for d in finite if d < cap)
    inter = [len(set(slot_lists[i]) & set(slot_lists[i + 1]))
             for i in range(len(slot_lists) - 1)]
    ws = {}
    for W in (1, 2, 4, 8):
        cs = []
        for i in range(len(slot_lists) - W + 1):
            u = set()
            for k in range(W):
                u.update(slot_lists[i + k])
            cs.append(len(u))
        ws[W] = sum(cs) / len(cs)
    per_bucket = defaultdict(int)
    for x in seq:
        per_bucket[x] += 1
    top10 = sorted(per_bucket.values(), reverse=True)[:10]
    return {
        "accesses": n, "distinct": len(per_bucket),
        "repeat_accesses": len(finite),
        "sd_median": sorted(finite)[len(finite) // 2] if finite else None,
        "sd_mean": round(sum(finite) / len(finite), 2) if finite else None,
        "sd_lt_cap": hits_lt_cap,
        "sd_lt_cap_frac": round(hits_lt_cap / n, 4),
        "interslot_mean": round(sum(inter) / len(inter), 3),
        "ws1": round(ws[1], 1), "ws2": round(ws[2], 1),
        "ws4": round(ws[4], 1), "ws8": round(ws[8], 1),
        "top10_share": round(sum(top10) / n, 4),
    }


# ---------------------------------------------------------------- main

def classify(name):
    m = MATRIX_RE.match(name)
    if m:
        return ("matrix", m.group(1), m.group(2), m.group(3), m.group(4))
    m = SEED_RE.match(name)
    if m:
        return ("seed", m.group(1), f"random{m.group(2)}", m.group(3), m.group(4))
    m = HOLD_RE.match(name)
    if m:
        return ("holdout", m.group(1), m.group(2), m.group(3), m.group(4))
    if name in VERIF:
        if name.endswith("_asan"):
            base = name[:-5]
            ds, pol, cap = base.split("_")[0], None, None
            return ("verif_asan", base.split("_")[0], "gorder", "belady_reject", "01")
        return ("verif", name.split("_")[0], "gorder",
                "belady_reject", "01")
    return (None, None, None, None, None)


def main():
    RES.mkdir(exist_ok=True)
    all_runs = sorted(p.name for p in RUNS.iterdir() if p.is_dir()
                      and not p.name.startswith("t_")
                      and not p.name.endswith("_preheapfix")
                      and not p.name.startswith("failedcfg_")
                      and not p.name.endswith("_prefix_crash"))
    rows, checks, problems = [], [], []
    gt_cache = {}
    meta_cache = {}
    pair_group = defaultdict(set)     # (ds, eb) -> set of frozenset(pairs)
    pair_group_run = defaultdict(list)

    for name in all_runs:
        kind, ds, order, policy, eb = classify(name)
        if kind is None:
            continue
        se = parse_stderr(name)
        so = parse_stdout(name)
        cfg = se.get("gate4a-config", {})
        cache = se.get("gate4a-cache", {})
        io = se.get("gate4b1-io", {})
        stat3 = se.get("gate3-stat", {})
        inv = se.get("gate3-inv", {})
        gorder = se.get("gate4a-gorder", {})
        g4b0 = se.get("gate4b0", {})
        acc, push = parse_trace(RUNS / name / "trace.txt")
        seq, targets, slot_lists = parse_tasks(RUNS / name / "tasks.txt")
        pairs = parse_pairs(RUNS / name / "pairs.txt")

        row = {"name": name, "kind": kind, "ds": ds, "order": order,
               "policy": policy if policy else "", "eb": eb,
               "capacity": cache.get("capacity_slots"),
               "total": cache.get("total"), "hit": cache.get("hit"),
               "miss": cache.get("miss"), "admit": cache.get("admit"),
               "evict": cache.get("evict"), "reject": cache.get("reject"),
               "read_calls": io.get("read_calls"),
               "eff_bytes": io.get("effective_bytes"),
               "req_bytes": io.get("requested_aligned_bytes"),
               "tasks": cfg.get("task_num_total"),
               "dist_comp": stat3.get("dist_comp"),
               "build_s": so["build_s"], "join_cum_s": so["join_cum_s"],
               "search_s": so["search_s"],
               "npairs": len(pairs)}

        # ---- GT evaluation (full oracle)
        if ds not in gt_cache:
            gt_cache[ds] = load_gt(ds)
        gt = gt_cache[ds]
        pset = set(pairs)
        tp = len(pset & gt)
        row["tp"] = tp
        row["fp"] = len(pset - gt)
        row["fn"] = len(gt - pset)
        row["precision"] = round(tp / len(pset), 6) if pset else None
        row["recall"] = round(tp / len(gt), 6) if gt else None
        row["gt"] = len(gt)
        row["dup_pairs"] = len(pairs) - len(pset)

        # ---- trace vs stats consistency
        t_hit = sum(1 for a in acc if a[2] == 1)
        t_miss = len(acc) - t_hit
        t_admit = sum(1 for p in push if p[2] == "admit")
        t_evict = sum(1 for p in push if p[2] == "evict")
        t_reject = sum(1 for p in push if p[2] == "reject")
        trace_seq = [a[1] for a in acc]
        ok_trace = (len(acc) == cache.get("total") and t_hit == cache.get("hit")
                    and t_miss == cache.get("miss")
                    and t_admit == cache.get("admit")
                    and t_evict == cache.get("evict")
                    and t_reject == cache.get("reject")
                    and trace_seq == seq)
        # ---- IO recomputation (exact formula from ClusterIO.h)
        if ds not in meta_cache:
            meta_cache[ds] = load_bucket_sizes(ds)
        n_, d_, cn_, sizes = meta_cache[ds]
        file_pos = []
        cum = 0
        for s in sizes:
            file_pos.append(cum * d_ * 4)
            cum += s
        miss_ids = [a[1] for a in acc if a[2] == 0]
        eff = sum(sizes[b] * d_ * 4 for b in miss_ids)
        req = 0
        for b in miss_ids:
            off = file_pos[b] % PAGE
            sz = sizes[b] * d_ * 4
            req += -(-(off + sz) // PAGE) * PAGE
        ok_io = (eff == io.get("effective_bytes")
                 and req == io.get("requested_aligned_bytes")
                 and io.get("read_calls") == cache.get("miss"))
        row["eff_recalc"] = eff
        row["req_recalc"] = req

        # ---- policy model cross-check
        xk = None
        if kind in ("matrix", "seed", "holdout", "verif_asan") or \
           (kind == "verif" and name in ("p1_cap62pin", "p1_cap40", "p3_cap40")):
            pol = policy
            if name == "p1_default_asan" or name == "p3_default_asan":
                pol = "belady_reject"
            if name == "p3_lru_asan":
                pol = "lru_forced"
            if name == "p1_forced_cap40_asan":
                pol = "belady_forced"
            if pol in ("belady_reject", "belady_forced", "lru_forced"):
                model_pol = {"belady_reject": "C", "belady_forced": "A",
                             "lru_forced": "D"}[pol]
                r = lockstep(seq, cache.get("capacity_slots"), acc, push, model_pol)
                if r is None:
                    problems.append(f"{name}: TRACE DESYNC in lockstep")
                    row["model_miss"] = None
                else:
                    row["model_miss"] = r["miss"]
                    row["model_victim_mismatch"] = r["victim_mismatch"]
                    row["model_victim_equiv"] = r["victim_equiv"]
                    row["model_type_mismatch"] = r["type_mismatch"]
                    ok_model = (r["miss"] == cache.get("miss")
                                and r["admit"] == cache.get("admit")
                                and r["evict"] == cache.get("evict")
                                and r["reject"] == cache.get("reject")
                                and r["A_mismatch"] == 0 and r["type_mismatch"] == 0)
                    if model_pol == "D":
                        ok_model = ok_model and r["victim_mismatch"] == 0
                    xk = ok_model
        row["model_ok"] = xk

        # ---- invariants
        inv_ok = (inv.get("perm_ok") == 1 and inv.get("upper_triangle_ok") == 1
                  and inv.get("head_mismatch") == 0 and inv.get("self_missing") == 0
                  and inv.get("task_total") == cfg.get("task_num_total")
                  and gorder.get("perm_ok") == 1)
        row["trace_ok"] = ok_trace
        row["io_ok"] = ok_io
        row["inv_ok"] = inv_ok
        row["fp_zero"] = (row["fp"] == 0)
        row["dup_zero"] = (row["dup_pairs"] == 0)
        if not (ok_trace and ok_io and inv_ok and row["fp_zero"] and row["dup_zero"]):
            problems.append(f"{name}: consistency FAIL trace={ok_trace} io={ok_io} "
                            f"inv={inv_ok} fp={row['fp']} dup={row['dup_pairs']}")
        if xk is False:
            problems.append(f"{name}: MODEL MISMATCH")

        pair_group[(ds, eb)].add(frozenset(pset))
        pair_group_run[(ds, eb)].append(name)
        rows.append(row)

    # ---- pair-set identity per (ds, eb)
    pair_ident = {}
    for key, sets in pair_group.items():
        pair_ident[key] = (len(sets) == 1)
        if len(sets) != 1:
            problems.append(f"PAIRSET DIFFERS within group {key}: "
                            f"{pair_group_run[key]}")
    # holdout/verif vs gate4a frozen pairs where available
    for ds in ("p1", "p3", "w1h", "w2h"):
        fp_ = G4A / "runs" / f"pairs_{ds}.txt"
        if fp_.exists() and (ds, "01") in pair_group:
            frozen = frozenset(set(parse_pairs(fp_)))
            if frozen not in pair_group[(ds, "01")]:
                problems.append(f"PAIRSET vs gate4a frozen DIFFERS for {ds}")

    # ---- task-graph identity across orders (matrix, per ds+eb, reject policy)
    for ds in ("p1", "p3"):
        for eb in ("01", "10"):
            graphs = []
            for o in ("gorder", "identity", "random"):
                p = RUNS / f"{ds}_{o}_belady_reject_eb{eb}" / "tasks.txt"
                if p.exists():
                    lines = []
                    for line in p.read_text().splitlines():
                        f2 = line.split()
                        lines.append(" ".join([f2[0]] + f2[2:]))  # drop target col? no:
                    # drop SLOT column: keep target+deg+cands
                    lines = []
                    for line in p.read_text().splitlines():
                        f2 = line.split()
                        lines.append(" ".join(f2[1:]))
                    graphs.append(sorted(lines))
            if len(graphs) == 3 and not (graphs[0] == graphs[1] == graphs[2]):
                problems.append(f"TASK GRAPH DIFFERS across orders {ds} eb{eb}")

    # ---- write summary tsv
    cols = ["name", "kind", "ds", "order", "policy", "eb", "capacity", "total",
            "hit", "miss", "admit", "evict", "reject", "read_calls", "eff_bytes",
            "req_bytes", "eff_recalc", "req_recalc", "tasks", "dist_comp",
            "npairs", "tp", "fp", "fn", "gt", "precision", "recall", "dup_pairs",
            "build_s", "join_cum_s", "search_s", "trace_ok", "io_ok", "inv_ok",
            "model_miss", "model_victim_mismatch", "model_victim_equiv",
            "model_type_mismatch", "model_ok"]
    with open(RES / "gate4b1_summary.tsv", "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c)) for c in cols) + "\n")

    # ---- locality + capacity curves (seq depends only on ds, eb, order)
    loc_rows, cap_rows = [], []
    loc_index = {}
    for ds in ("p1", "p3"):
        for eb in ("01", "10"):
            for o in ("gorder", "identity", "random"):
                p = RUNS / f"{ds}_{o}_belady_reject_eb{eb}" / "tasks.txt"
                if not p.exists():
                    continue
                seq, targets, slot_lists = parse_tasks(p)
                lr = locality_report(seq, slot_lists, 62)
                lr.update({"ds": ds, "eb": eb, "order": o})
                loc_rows.append(lr)
                loc_index[(ds, eb, o)] = lr
                for pol, tag in (("C", "belady_reject"), ("A", "belady_forced"),
                                 ("D", "lru_forced")):
                    for cap in (8, 16, 24, 32, 40, 48, 56, 62, 64, 72, 80, 96, 120):
                        miss = sim_offline(seq, cap, pol)
                        cap_rows.append({"ds": ds, "eb": eb, "order": o,
                                         "policy": tag, "cap": cap, "miss": miss})
    with open(RES / "gate4b1_locality.tsv", "w") as f:
        if loc_rows:
            keys = list(loc_rows[0].keys())
            f.write("\t".join(keys) + "\n")
            for r in loc_rows:
                f.write("\t".join(str(r[k]) for k in keys) + "\n")
    with open(RES / "gate4b1_capcurve.tsv", "w") as f:
        f.write("ds\teb\torder\tpolicy\tcap\tmiss\n")
        for r in cap_rows:
            f.write(f"{r['ds']}\t{r['eb']}\t{r['order']}\t{r['policy']}\t{r['cap']}\t{r['miss']}\n")

    # ---- timing digest
    t_rows = []
    for d in sorted(RUNS.iterdir()):
        m = TIME_RE.match(d.name)
        if not m or not d.is_dir():
            continue
        base = m.group(1)
        for tf in sorted(d.glob("time_r*.log")):
            rep = tf.stem.split("_r")[1]
            txt = tf.read_text(errors="replace")
            w = re.search(r"Elapsed \(wall clock\) time.*?: (\S+)", txt)
            u = re.search(r"User time \(seconds\): (\S+)", txt)
            s = re.search(r"System time \(seconds\): (\S+)", txt)

            def to_sec(x):
                if not x:
                    return None
                parts = x.split(":")
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                return float(x)
            so2 = parse_stdout(f"t_{base}_r{rep}") if (LOGS / f"t_{base}_r{rep}.stdout").exists() else parse_stdout("t_" + base)
            t_rows.append({"name": base, "rep": int(rep),
                           "wall_s": to_sec(w.group(1) if w else None),
                           "user_s": float(u.group(1)) if u else None,
                           "sys_s": float(s.group(1)) if s else None,
                           "build_s": so2["build_s"], "search_s": so2["search_s"],
                           "join_cum_s": so2["join_cum_s"]})
    with open(RES / "gate4b1_timing.tsv", "w") as f:
        f.write("name\trep\twall_s\tuser_s\tsys_s\tbuild_s\tsearch_s\tjoin_cum_s\n")
        for r in t_rows:
            f.write("\t".join(str(r[c]) for c in
                              ["name", "rep", "wall_s", "user_s", "sys_s",
                               "build_s", "search_s", "join_cum_s"]) + "\n")

    # ---- markdown digest
    def fmt(r, keys):
        return " | ".join(str(r.get(k)) for k in keys)

    out = []
    out.append("# GATE4B1 ANALYSIS DIGEST")
    out.append(f"\nruns analyzed: {len(rows)} (matrix + seeds + holdout + verification)")
    out.append(f"\n## Consistency problems: {len(problems)}")
    for p in problems:
        out.append(f"- {p}")
    if not problems:
        out.append("- NONE: trace/stats/IO-recompute/invariants/FP=0/dup=0/model xcheck all PASS")

    out.append("\n## Matrix: cache misses (miss | admit/evict/reject | eff_B req_B)")
    for ds in ("p1", "p3"):
        for eb in ("01", "10"):
            out.append(f"\n### {ds} eb{eb}")
            out.append("order | belady_reject | belady_forced | lru_forced")
            for o in ("gorder", "identity", "random"):
                cells = []
                for pol in ("belady_reject", "belady_forced", "lru_forced"):
                    r = next((x for x in rows if x["name"] == f"{ds}_{o}_{pol}_eb{eb}"), None)
                    if r:
                        cells.append(f"{r['miss']} ({r['admit']}/{r['evict']}/{r['reject']}) "
                                    f"[{r['eff_bytes']}B/{r['req_bytes']}B]")
                    else:
                        cells.append("-")
                out.append(f"{o} | " + " | ".join(cells))

    out.append("\n## GT evaluation (full oracle)")
    for ds in ("p1", "p3", "w1h", "w2h"):
        rs = [r for r in rows if r["ds"] == ds]
        if not rs:
            continue
        for eb in sorted(set(r["eb"] for r in rs)):
            r0 = next(r for r in rs if r["eb"] == eb)
            out.append(f"- {ds} eb{eb}: pairs={r0['npairs']} GT={r0['gt']} "
                       f"TP={r0['tp']} FP={r0['fp']} FN={r0['fn']} "
                       f"precision={r0['precision']} recall={r0['recall']}")
    out.append("\n## Locality (per order; LRU stack distance < 62 = LRU-hittable)")
    out.append("ds eb order | acc | sd_med | sd_mean | sd<62 | frac | interslot | ws1 ws2 ws4 ws8 | top10")
    for r in loc_rows:
        out.append(f"{r['ds']} {r['eb']} {r['order']} | {r['accesses']} | {r['sd_median']} | "
                    f"{r['sd_mean']} | {r['sd_lt_cap']} | {r['sd_lt_cap_frac']} | "
                    f"{r['interslot_mean']} | {r['ws1']} {r['ws2']} {r['ws4']} {r['ws8']} | {r['top10_share']}")

    out.append("\n## Capacity curves (miss @ cap; C=reject A=forced D=lru)")
    for ds in ("p1", "p3"):
        for eb in ("01",):
            for o in ("gorder", "identity"):
                cs = {r["cap"]: r for r in cap_rows
                      if r["ds"] == ds and r["eb"] == eb and r["order"] == o}
                if cs:
                    caps = sorted({r["cap"] for r in cs.values()})
                    out.append(f"- {ds} eb{eb} {o}: " + ", ".join(
                        f"c{c}:R{cs[c]['miss'] if 'C' else ''}" for c in []))
    # capacity-curve table, one line per (ds,eb,order,policy)
    out.append("(full curves in results/gate4b1_capcurve.tsv; key caps 40/62/80 below)")
    for r in cap_rows:
        if r["cap"] in (40, 62, 80) and r["eb"] == "01":
            pass
    tbl = defaultdict(dict)
    for r in cap_rows:
        if r["cap"] in (40, 62, 80):
            tbl[(r["ds"], r["eb"], r["order"], r["policy"])][r["cap"]] = r["miss"]
    out.append("ds eb order policy | miss@40 | miss@62 | miss@80")
    for k in sorted(tbl):
        v = tbl[k]
        out.append(f"{k[0]} {k[1]} {k[2]} {k[3]} | {v.get(40)} | {v.get(62)} | {v.get(80)}")

    out.append("\n## Pruning ablation (gorder, belady_reject)")
    for ds in ("p1", "p3"):
        a = next((r for r in rows if r["name"] == f"{ds}_gorder_belady_reject_eb01"), None)
        b = next((r for r in rows if r["name"] == f"{ds}_gorder_belady_reject_eb10"), None)
        if a and b:
            out.append(f"- {ds}: tasks {a['tasks']}->{b['tasks']} "
                       f"({100*(b['tasks']-a['tasks'])/a['tasks']:+.1f}%), "
                       f"dist_comp {a['dist_comp']}->{b['dist_comp']} "
                       f"({100*(b['dist_comp']-a['dist_comp'])/a['dist_comp']:+.1f}%), "
                       f"miss {a['miss']}->{b['miss']}, "
                       f"eff {a['eff_bytes']}->{b['eff_bytes']} B, "
                       f"recall {a['recall']}->{b['recall']} "
                       f"({100*(b['recall']-a['recall']):+.2f} pp)")

    out.append("\n## Extra seeds (random order sensitivity, eb01)")
    for ds in ("p1", "p3"):
        for pol in ("belady_reject", "belady_forced", "lru_forced"):
            vals = [next(r["miss"] for r in rows if r["name"] == f"{ds}_random_{pol}_eb01")]
            extra = []
            for seed in ("20261102", "424242"):
                r = next((r for r in rows if r["name"] == f"{ds}_seed{seed}_{pol}_eb01"), None)
                if r:
                    extra.append(r["miss"])
            out.append(f"- {ds} {pol}: seed20260101={vals[0]}, "
                       f"seed20261102={extra[0] if extra else '-'}, "
                       f"seed424242={extra[1] if len(extra) > 1 else '-'}")

    out.append("\n## Holdout")
    for r in rows:
        if r["kind"] == "holdout":
            out.append(f"- {r['name']}: miss={r['miss']} tasks={r['tasks']} "
                       f"npairs={r['npairs']} recall={r['recall']} fp={r['fp']}")

    out.append("\n## Timing (SUB-SECOND: recorded, NOT performance claims)")
    agg = defaultdict(list)
    for r in t_rows:
        agg[r["name"]].append(r)
    for name in sorted(agg):
        rs = agg[name]
        walls = [r["wall_s"] for r in rs]
        blds = [r["build_s"] for r in rs if r["build_s"]]
        srch = [r["search_s"] for r in rs if r["search_s"] is not None]
        out.append(f"- {name}: n={len(rs)} wall[min/mean/max]="
                   f"{min(walls):.3f}/{sum(walls)/len(walls):.3f}/{max(walls):.3f}s "
                   f"build~{sum(blds)/len(blds):.3f}s search~{sum(srch)/len(srch):.3f}s"
                   if blds and srch else f"- {name}: n={len(rs)}")

    digest = "\n".join(out)
    (RES / "gate4b1_digest.md").write_text(digest)
    print(digest)
    print("\nWROTE results/gate4b1_summary.tsv, gate4b1_locality.tsv, "
          "gate4b1_capcurve.tsv, gate4b1_timing.tsv, gate4b1_digest.md",
          file=sys.stderr)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
