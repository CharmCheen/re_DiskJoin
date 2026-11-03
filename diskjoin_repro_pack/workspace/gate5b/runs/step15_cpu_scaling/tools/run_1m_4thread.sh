#!/usr/bin/env bash
# Step 15 — one 1M 4-thread join with the per-thread streaming sink.
#
# Uses the step15 build (step13-verified C path + GATE15 output-only sink).
# Fixed graph/tasks/config (step13 1M graph; GATE14_SKIP_BUILD=1), so the only
# varying factor is the compute-region thread count = 4. Compute logic is
# unchanged; only the pair OUTPUT sink is the bounded per-thread stream.
#
# Threads on nested physical cores {2,3,4,5} of NUMA node 0.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step15_cpu_scaling"
BIN="$R/build/main"
FB="$ROOT/acq1m/data/bigann1m.fbin"
G="$ROOT/runs/step13_c_integration/graph"
D="$R/correctness_1m/t4"
mkdir -p "$D"

cat > "$D/config" <<EOF
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

echo "=== [1M t=4 cpus=2,3,4,5] START $(date -Is) ===" | tee -a "$R/logs/driver.log"
taskset -c 2,3,4,5 env OMP_NUM_THREADS=4 OMP_PROC_BIND=true OMP_PLACES=cores \
  OMP_DISPLAY_AFFINITY=TRUE \
  GATE14_SKIP_BUILD=1 GATE13_C_PATH=1 GATE4B0_WINDOW=2 \
  GATE3_PAIR_OUT="$D/pairs.txt" GATE15_PER_THREAD_STREAM=1 \
  GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 GATE5B_PROFILE=1 GATE14_EXACT_COUNT=1 \
  /usr/bin/time -v timeout 1500 "$BIN" "$D/config" \
  > "$D/stdout.log" 2> "$D/stderr.log"
echo "$?" > "$D/rc.txt"
echo "=== [1M t=4] END $(date -Is) rc=$(cat "$D/rc.txt") ===" | tee -a "$R/logs/driver.log"

echo "--- per-thread sink files ---"
ls -la "$D"/pairs.txt.t* 2>/dev/null
echo "--- gate15 line ---"; grep -h '\[gate15\]' "$D/stderr.log"
echo "--- invariants ---"; grep -hE '\[gate14-exact\]|\[gate3-stat\]|\[gate4b1-io\]|recall' "$D/stdout.log" "$D/stderr.log"
echo "--- time -v peak RSS / elapsed / CPU% ---"
grep -E 'Elapsed|Maximum resident|Percent of CPU' "$D/stderr.log"
