#!/usr/bin/env python3
"""Gate 4B-0 Task 2: cache-policy semantics audit on the frozen P1/P3 traces.

Explains exactly why   C++ miss (P1: 172, P3: 164)  <  forced-load offline
Belady (174/165)  <  LRU (301/273).

Models (identical access sequence, capacity, initial state and miss
definition = "access to a non-resident bucket"; every miss triggers exactly
one admission decision):

  A  forced-load Belady (classic OPT *within the forced action set*):
     on every miss the bucket MUST be inserted; when full, the resident with
     the farthest next use is evicted. This is the gate4a
     trace_policy_sim.py "belady" policy. Provably optimal in the forced
     action set (Belady's MIN argument).
  B  rejection-allowed offline optimum *within the reject action set*:
     on a miss the policy may insert (evicting any resident) or skip.
     Exact only via small-scale DP here; on the full trace we simulate the
     greedy rule and label it as such (greedy-B), never as exact OPT.
  C  exact replication of the C++ Cache policy (Cache::find/push in
     lib/Cache.h): ptr/iters future-use bookkeeping with SIZE_MAX sentinel;
     on hit, priority.update(next use); on miss, push -> cold admit /
     evict farthest-next-use iff strictly farther than incoming / reject.
     Verified decision-for-decision against the GATE4A_CACHE_TRACE.
  D  forced-load LRU: on every miss insert, evict least-recently-used.
     Same feasible action set as A (only the victim rule differs).

Everything read-only. Pure stdlib.
"""
import json
import sys
from pathlib import Path

WS = Path("/home/qch/DiskJoin/diskjoin_repro_pack/workspace")
G4B0 = WS / "gate4b0" / "runs"

DATASETS = {
    "p1": {"trace": G4B0 / "p1_default/trace.txt",
           "tasks": G4B0 / "p1_default/tasks.txt",
           "frozen_trace": WS / "gate4a/runs/p1_small_cachetrace.txt",
           "expect": {"A": 174, "B": 172, "C": 172, "D": 301}},
    "p3": {"trace": G4B0 / "p3_default/trace.txt",
           "tasks": G4B0 / "p3_default/tasks.txt",
           "frozen_trace": WS / "gate4a/runs/p3_small_cachetrace.txt",
           "expect": {"A": 165, "B": 164, "C": 164, "D": 273}},
}

SENTINEL = None  # python None plays the role of SIZE_MAX (never again)


# ---------------------------------------------------------------- parsing

def parse_trace(path):
    """Return (accesses, pushes): accesses = [(seq, id, hit)],
    pushes = [(seq, id, action, victim)]."""
    accesses, pushes = [], []
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "A":
                accesses.append((int(p[1]), int(p[2]), int(p[3])))
            elif p[0] == "P":
                pushes.append((int(p[1]), int(p[2]), p[3], int(p[4])))
    return accesses, pushes


def access_seq_from_tasks(path):
    """Rebuild the cache access sequence from the GATE4A task dump: for each
    slot (in slot order) the target's list [head, neighbours...] is loaded
    through Cache::find in list order."""
    lists = {}
    with open(path) as f:
        for line in f:
            p = [int(x) for x in line.split()]
            slot, deg = p[0], p[2]
            lists[slot] = p[3:3 + deg]
    seq = []
    for slot in sorted(lists):
        seq.extend(lists[slot])
    return seq


def next_use_table(seq):
    """nxt[i] = next position > i with seq[i] == seq[nxt[i]], else None."""
    nxt = [SENTINEL] * len(seq)
    last = {}
    for i in range(len(seq) - 1, -1, -1):
        nxt[i] = last.get(seq[i], SENTINEL)
        last[seq[i]] = i
    return nxt


# ---------------------------------------------------------------- models

def vickey(nu, v):
    """Victim-selection key: farthest next use; SENTINEL (never again) plays
    the role of SIZE_MAX = +infinity in the C++ heap (std::greater max-heap),
    so never-again residents are evicted first. Ties (only sentinel ties are
    possible) break to the smaller id."""
    return (2, 0, -v) if nu is SENTINEL else (1, nu, -v)


def sim_forced_belady(seq, cap):
    """Model A: forced-load Belady (farthest-next-use eviction)."""
    nxt = next_use_table(seq)
    res = {}          # id -> next use
    miss = hit = 0
    for i, x in enumerate(seq):
        if x in res:
            hit += 1
            res[x] = nxt[i]
        else:
            miss += 1
            if len(res) >= cap:
                victim = max(res, key=lambda v: vickey(res[v], v))
                del res[victim]
            res[x] = nxt[i]
    return {"miss": miss, "hit": hit, "accesses": len(seq)}


def sim_greedy_reject(seq, cap):
    """Model B (greedy rule; identical to the C++ rule):
    cold-admit when not full; else evict the farthest-next-use resident iff
    its next use is strictly later than the incoming's; otherwise reject."""
    nxt = next_use_table(seq)
    res = {}
    miss = hit = 0
    admit = evict = reject = 0
    for i, x in enumerate(seq):
        if x in res:
            hit += 1
            res[x] = nxt[i]
        else:
            miss += 1
            if len(res) < cap:
                res[x] = nxt[i]
                admit += 1
            else:
                vfar = max(res, key=lambda v: vickey(res[v], v))
                nu_in = nxt[i]
                vfar_nu = res[vfar]
                better = (nu_in is not SENTINEL and vfar_nu is SENTINEL) or \
                         (nu_in is not SENTINEL and vfar_nu is not SENTINEL
                          and vfar_nu > nu_in)
                if better:
                    del res[vfar]
                    res[x] = nu_in
                    evict += 1
                else:
                    reject += 1
    return {"miss": miss, "hit": hit, "accesses": len(seq),
            "admit": admit, "evict": evict, "reject": reject}


def sim_forced_lru(seq, cap):
    """Model D: forced-load LRU (same feasible action set as A)."""
    res = {}          # id -> last use position
    miss = hit = 0
    for i, x in enumerate(seq):
        if x in res:
            hit += 1
            res[x] = i
        else:
            miss += 1
            if len(res) >= cap:
                victim = min(res, key=lambda v: res[v])
                del res[victim]
            res[x] = i
    return {"miss": miss, "hit": hit, "accesses": len(seq)}


def model_C_cpp(seq, cap, trace_accesses, trace_pushes):
    """Exact replication of the C++ Cache (find/push), cross-checked against
    the trace. Returns stats + mismatch counters."""
    # iters/ptr exactly as Cache::init
    iters = {}
    for pos, x in enumerate(seq):
        iters.setdefault(x, []).append(pos)
    ptr = {x: 0 for x in iters}
    for x in iters:
        iters[x].append(SENTINEL)
    res = {}   # id -> next use (mirrors priority heap keys)
    total = hit = miss = admit = evict = reject = 0
    ev_A_mismatch = ev_P_type_mismatch = ev_P_victim_mismatch = 0
    ev_P_victim_neveragain_equiv = 0
    push_iter = iter(trace_pushes)
    for i, x in enumerate(seq):
        ptr[x] += 1
        nu = iters[x][ptr[x]]
        total += 1
        tr = trace_accesses[i]
        assert tr[0] == total and tr[1] == x, f"trace desync at {i}"
        if x in res:
            hit += 1
            res[x] = nu
            if tr[2] != 1:
                ev_A_mismatch += 1
        else:
            miss += 1
            if tr[2] != 0:
                ev_A_mismatch += 1
            # push
            tp = next(push_iter)
            assert tp[0] == total and tp[1] == x, f"push desync at {i}"
            if len(res) < cap:
                res[x] = nu
                admit += 1
                if tp[2] != "admit":
                    ev_P_type_mismatch += 1
            else:
                # farthest resident (SENTINEL = SIZE_MAX = +infinity);
                # tie -> smallest id (only sentinel ties can occur)
                vfar = max(res, key=lambda v: vickey(res[v], v))
                nu_in = nu
                vfar_nu = res[vfar]
                better = (nu_in is not SENTINEL and vfar_nu is SENTINEL) or \
                         (nu_in is not SENTINEL and vfar_nu is not SENTINEL
                          and vfar_nu > nu_in)
                if better:
                    del res[vfar]
                    res[x] = nu_in
                    evict += 1
                    if tp[2] != "evict":
                        ev_P_type_mismatch += 1
                    elif tp[3] != vfar:
                        # interchangeable iff BOTH victims are never used
                        # again (their future hit/miss impact is identical);
                        # judged from the exact iters/ptr future-use index,
                        # independent of residency bookkeeping drift
                        tv_nu = iters[tp[3]][ptr[tp[3]]]
                        if tv_nu is SENTINEL and vfar_nu is SENTINEL:
                            ev_P_victim_neveragain_equiv += 1
                        else:
                            ev_P_victim_mismatch += 1
                else:
                    reject += 1
                    if tp[2] != "reject":
                        ev_P_type_mismatch += 1
    return {"miss": miss, "hit": hit, "accesses": total, "admit": admit,
            "evict": evict, "reject": reject,
            "A_line_mismatches": ev_A_mismatch,
            "P_type_mismatches": ev_P_type_mismatch,
            "P_victim_mismatches": ev_P_victim_mismatch,
            "P_victim_neveragain_equivalent": ev_P_victim_neveragain_equiv}


# ------------------------------------------------------- divergence chains

def divergence_chains(seq, cap):
    """Lockstep A (forced Belady) vs C (greedy reject = the C++ rule).

    A chain is a maximal interval of positions where the resident sets
    differ (before or after the step). The sum of per-chain
    (missA - missC) deltas equals the global miss difference; a chain starts
    at a miss where C rejected while A evicted+admitted."""
    nxt = next_use_table(seq)
    resA, resC = {}, {}
    chains = []
    cur = None
    missA = missC = 0

    def step_forced(res, i, x):
        # forced Belady step (model A)
        hit = x in res
        if hit:
            res[x] = nxt[i]
        else:
            if len(res) >= cap:
                victim = max(res, key=lambda v: vickey(res[v], v))
                del res[victim]
            res[x] = nxt[i]
        return hit

    def step_reject(res, i, x):
        # greedy reject step (model C / the C++ Cache rule)
        hit = x in res
        if hit:
            res[x] = nxt[i]
        else:
            if len(res) < cap:
                res[x] = nxt[i]
            else:
                vfar = max(res, key=lambda v: vickey(res[v], v))
                nu_in = nxt[i]
                vfar_nu = res[vfar]
                better = (nu_in is not SENTINEL and vfar_nu is SENTINEL) or \
                         (nu_in is not SENTINEL and vfar_nu is not SENTINEL
                          and vfar_nu > nu_in)
                if better:
                    del res[vfar]
                    res[x] = nu_in
        return hit

    for i, x in enumerate(seq):
        diff_before = resA != resC
        hitA = step_forced(resA, i, x)
        missA += 0 if hitA else 1
        hitC = step_reject(resC, i, x)
        missC += 0 if hitC else 1
        diff_after = resA != resC
        if diff_before or diff_after:
            if cur is None:
                cur = {"start": i, "events": []}
                chains.append(cur)
            cur["end"] = i
            cur["events"].append({
                "i": i, "x": x, "hitA": hitA, "hitC": hitC,
                "resA_only": sorted(set(resA) - set(resC)),
                "resC_only": sorted(set(resC) - set(resA))})
        else:
            cur = None

    total_delta = 0
    for ch in chains:
        delta = sum((0 if e["hitA"] else 1) - (0 if e["hitC"] else 1)
                    for e in ch["events"])
        ch["miss_delta_A_minus_C"] = delta
        total_delta += delta
    assert total_delta == missA - missC, \
        f"chain deltas {total_delta} != global {missA - missC}"
    return {"missA": missA, "missC": missC, "chains": chains}


# ---------------------------------------------------------------- small DP

def dp_opt(seq, cap, allow_reject):
    """Exact offline DP on a small trace prefix. allow_reject=False gives
    the forced action set (insert mandatory on miss); True adds the skip
    action. Objective: minimise total misses."""
    cur = {frozenset(): 0}
    for i, x in enumerate(seq):
        nxt_states = {}
        for S, cost in cur.items():
            if x in S:
                nxt_states[S] = min(nxt_states.get(S, 1 << 60), cost)
            else:
                c2 = cost + 1
                if len(S) < cap:
                    key = S | {x}
                    nxt_states[key] = min(nxt_states.get(key, 1 << 60), c2)
                else:
                    for v in S:
                        key = (S - {v}) | {x}
                        nxt_states[key] = min(nxt_states.get(key, 1 << 60), c2)
                    if allow_reject:
                        nxt_states[S] = min(nxt_states.get(S, 1 << 60), c2)
        cur = nxt_states
    return min(cur.values())


def minimal_counterexample():
    """Hand-crafted minimal trace where forced-load loses vs rejection.
    capacity = 1, trace ids [0, 1, 0] (id 1 is never accessed again):
      forced Belady: 0(miss,insert) 1(miss,evict 0,insert 1) 0(miss) -> 3 misses
      greedy reject: 0(miss,insert) 1(miss,reject)          0(hit)  -> 2 misses
    Verified with both greedy rules and the exact DP."""
    tr = [0, 1, 0]
    forced = sim_forced_belady(tr, 1)
    greedy = sim_greedy_reject(tr, 1)
    dp_forced = dp_opt(tr, 1, False)
    dp_reject = dp_opt(tr, 1, True)
    return {"trace": "0 1 0 (1 never used again)", "capacity": 1,
            "forced_belady_misses": forced["miss"],
            "greedy_reject_misses": greedy["miss"],
            "dp_forced_opt": dp_forced, "dp_reject_opt": dp_reject}


def main():
    out = {}
    ok_all = True
    for ds, spec in DATASETS.items():
        accesses, pushes = parse_trace(spec["trace"])
        # 0. cross-checks of the trace itself
        task_seq = access_seq_from_tasks(spec["tasks"])
        trace_seq = [a[1] for a in accesses]
        recon_ok = task_seq == trace_seq
        cap = sum(1 for p in pushes if p[2] == "admit")  # cold admits == cap
        frozen_same = spec["trace"].read_bytes() == spec["frozen_trace"].read_bytes()

        res = {
            "accesses": len(accesses),
            "pushes": len(pushes),
            "trace_reconstruction_from_tasks_ok": recon_ok,
            "trace_equals_frozen_gate4a": frozen_same,
            "derived_capacity": cap,
            "trace_miss": sum(1 for a in accesses if a[2] == 0),
            "trace_evict": sum(1 for p in pushes if p[2] == "evict"),
            "trace_reject": sum(1 for p in pushes if p[2] == "reject"),
        }
        # 1. models
        res["A_forced_belady"] = sim_forced_belady(trace_seq, cap)
        res["B_greedy_reject"] = sim_greedy_reject(trace_seq, cap)
        res["C_cpp_replica"] = model_C_cpp(trace_seq, cap, accesses, pushes)
        res["D_forced_lru"] = sim_forced_lru(trace_seq, cap)
        # 2. A-vs-C divergence chains
        div = divergence_chains(trace_seq, cap)
        chains = []
        for ch in div["chains"]:
            chains.append(ch)
        res["divergence"] = {
            "missA": div["missA"], "missC": div["missC"],
            "n_chains": len(chains),
            "chains": chains,
        }
        # 3. small-scale exact DP on prefixes
        dp_rows = []
        for T, c in ((40, 2), (40, 3), (60, 2), (80, 2)):
            prefix = trace_seq[:T]
            row = {"prefix": T, "cap": c,
                   "distinct": len(set(prefix)),
                   "dp_forced_opt": dp_opt(prefix, c, False),
                   "greedy_A": sim_forced_belady(prefix, c)["miss"],
                   "dp_reject_opt": dp_opt(prefix, c, True),
                   "greedy_B": sim_greedy_reject(prefix, c)["miss"]}
            dp_rows.append(row)
        res["dp_small"] = dp_rows
        res["minimal_counterexample"] = minimal_counterexample()

        # ---- verdicts
        checks = {
            "reconstruction_ok": recon_ok,
            "trace_frozen_identical": frozen_same,
            "C_A_lines_match": res["C_cpp_replica"]["A_line_mismatches"] == 0,
            "C_P_types_match": res["C_cpp_replica"]["P_type_mismatches"] == 0,
            "C_P_victims_ok": res["C_cpp_replica"]["P_victim_mismatches"] == 0,
            "C_miss_equals_trace": res["C_cpp_replica"]["miss"] == res["trace_miss"],
            "A_equals_expected": res["A_forced_belady"]["miss"] == spec["expect"]["A"],
            "B_equals_expected": res["B_greedy_reject"]["miss"] == spec["expect"]["B"],
            "C_equals_expected": res["C_cpp_replica"]["miss"] == spec["expect"]["C"],
            "D_equals_expected": res["D_forced_lru"]["miss"] == spec["expect"]["D"],
        }
        res["checks"] = checks
        ok = all(checks.values())
        ok_all = ok_all and ok
        out[ds] = res
        print(f"[{ds}] cap={cap} accesses={res['accesses']} "
              f"trace_miss={res['trace_miss']} "
              f"(evict={res['trace_evict']} reject={res['trace_reject']})")
        print(f"    A(forced Belady)={res['A_forced_belady']['miss']}  "
              f"B(greedy reject)={res['B_greedy_reject']['miss']}  "
              f"C(C++ replica)={res['C_cpp_replica']['miss']}  "
              f"D(forced LRU)={res['D_forced_lru']['miss']}")
        print(f"    C-vs-trace: A_mismatch={res['C_cpp_replica']['A_line_mismatches']} "
              f"P_type={res['C_cpp_replica']['P_type_mismatches']} "
              f"P_victim={res['C_cpp_replica']['P_victim_mismatches']} "
              f"(never-again-equiv={res['C_cpp_replica']['P_victim_neveragain_equivalent']})")
        print(f"    divergence chains={res['divergence']['n_chains']} "
              f"missA-missC={res['divergence']['missA'] - res['divergence']['missC']}")
        for row in dp_rows:
            print(f"    DP prefix={row['prefix']} cap={row['cap']}: "
                  f"forced_opt={row['dp_forced_opt']} greedyA={row['greedy_A']} "
                  f"reject_opt={row['dp_reject_opt']} greedyB={row['greedy_B']}")
        print(f"    checks: {checks}")
    out["ok_all"] = ok_all
    dst = WS / "gate4b0" / "results" / "cache_models.json"
    dst.parent.mkdir(exist_ok=True)
    with open(dst, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{'PASS' if ok_all else 'FAIL'} -> {dst}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
