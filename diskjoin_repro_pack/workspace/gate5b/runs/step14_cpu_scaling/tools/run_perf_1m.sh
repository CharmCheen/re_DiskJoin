#!/usr/bin/env bash
# Step 14 — BigANN1M compute-thread scaling: 1 / 2 / 4 threads, 3 runs each.
#
# Fixed: step13-verified C path (GATE13_C_PATH=1), BigANN1M, radius 73984,
# cluster_num 1000, K 24, error_bound 0.1, gt 8379, GATE4B0_WINDOW=2, 10% cache
# (mem_budget 0.0476837158203125). pair/trace output OFF (GATE3_COUNT_ONLY).
#
# BUILD IS SKIPPED (GATE14_SKIP_BUILD=1) and the fixed verified step13 1M graph
# is reused, so the ONLY varying factor is the compute-region thread count.
#   * The build phase is not deterministic across threads (concurrent HNSW
#     insert), so a per-run rebuild would silently change graph/tasks.
#   * Build threads/timing are recorded separately (see build_1thread.log).
#
# Nested physical core sets on NUMA node 0: 1 -> {2}, 2 -> {2,3}, 4 -> {2,3,4,5}.
# Rotation order per requirement: 1/2/4, 2/4/1, 4/1/2.
# Same timing method for all runs: GATE5B_PROFILE (compute/search wall+cpu) and
# /usr/bin/time -v (process elapsed, CPU%, peak RSS). No concurrent timing.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step14_cpu_scaling"
BIN="$R/build/main"
FB="$ROOT/acq1m/data/bigann1m.fbin"
G="$ROOT/runs/step13_c_integration/graph"   # fixed verified 1M graph
P="$R/perf"
mkdir -p "$P"

cpus_for() { case "$1" in 1) echo "2";; 2) echo "2,3";; 4) echo "2,3,4,5";; esac; }

run_one() { # $1 = run label, $2 = threads
  local label="$1" t="$2" cpus d
  cpus="$(cpus_for "$t")"; d="$P/$label"; mkdir -p "$d"
  cat > "$d/config" <<EOF
data_file $FB
radius 73984
cluster_num 1000
cluster_file $G/data.clusters
metadata_file $G/data.metadata
hnsw_file $G/data.hnsw
K 24
mem_budget 0.0476837158203125
error_bound 0.1
gt 8379
EOF
  echo "=== [$label t=$t cpus=$cpus] START $(date -Is) ===" | tee -a "$R/logs/driver.log"
  taskset -c "$cpus" env OMP_NUM_THREADS="$t" OMP_PROC_BIND=true OMP_PLACES=cores \
    OMP_DISPLAY_AFFINITY=TRUE \
    GATE14_SKIP_BUILD=1 GATE13_C_PATH=1 GATE4B0_WINDOW=2 \
    GATE3_PAIR_OUT="$d/count_sink_unused" GATE3_COUNT_ONLY=1 \
    GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 GATE5B_PROFILE=1 GATE14_EXACT_COUNT=1 \
    /usr/bin/time -v timeout 1200 "$BIN" "$d/config" \
    > "$d/stdout.log" 2> "$d/stderr.log"
  echo "$?" > "$d/rc.txt"
  echo "=== [$label t=$t] END $(date -Is) rc=$(cat "$d/rc.txt") ===" | tee -a "$R/logs/driver.log"
}

# rotation: 1/2/4, 2/4/1, 4/1/2
run_one r1_t1 1
run_one r2_t2 2
run_one r3_t4 4
run_one r4_t2 2
run_one r5_t4 4
run_one r6_t1 1
run_one r7_t4 4
run_one r8_t1 1
run_one r9_t2 2

echo "--- all perf runs done $(date -Is) ---" | tee -a "$R/logs/driver.log"
