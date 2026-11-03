#!/usr/bin/env bash
# Step 13 — end-to-end 1M performance comparison: baseline (A) vs C path.
#
# Fixed config: 10% cache (mem_budget 0.0476837158203125), radius 73984,
# cluster_num 1000, K 24, error_bound 0.1, gt 8379, GATE4B0_WINDOW=2,
# OMP_NUM_THREADS=1, taskset -c 2. Pair/trace output OFF (GATE3_COUNT_ONLY).
# Same binary, same counters, same GATE5B_PROFILE phase timing for both.
# Run order alternates A/C/C/A/A/C (3 each), as required.
#
# A = baseline (GATE13_C_PATH unset)   C = C path (GATE13_C_PATH=1)
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step13_c_integration"
BIN="$R/build/main"
CPU="${PIN_CPU:-2}"
FB="$ROOT/acq1m/data/bigann1m.fbin"
G="$R/graph"
P="$R/perf"
mkdir -p "$G" "$P" "$R/logs"

run_one() { # label variant(A|C)
  local label="$1" variant="$2"
  local d="$P/$label"; mkdir -p "$d"
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
  local cpath=""
  [ "$variant" = C ] && cpath="GATE13_C_PATH=1"
  echo "=== [$label/$variant] START $(date -Is) ===" | tee -a "$R/logs/driver.log"
  taskset -c "$CPU" env OMP_NUM_THREADS=1 GATE4B0_WINDOW=2 $cpath \
    GATE3_PAIR_OUT="$d/count_sink_unused" GATE3_COUNT_ONLY=1 \
    GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
    GATE4A_TASK_OUT="$d/tasks.txt" GATE5B_PROFILE=1 \
    /usr/bin/time -v timeout 1500 "$BIN" "$d/config" \
    > "$d/stdout.log" 2> "$d/stderr.log"
  echo "$?" > "$d/rc.txt"
  echo "=== [$label/$variant] END $(date -Is) rc=$(cat "$d/rc.txt") ===" | tee -a "$R/logs/driver.log"
}

# required alternating order A/C, C/A, A/C
run_one r01_A A
run_one r02_C C
run_one r03_C C
run_one r04_A A
run_one r05_A A
run_one r06_C C

echo "--- all runs done $(date -Is) ---"
