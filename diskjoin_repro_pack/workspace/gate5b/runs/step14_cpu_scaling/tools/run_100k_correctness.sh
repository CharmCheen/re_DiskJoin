#!/usr/bin/env bash
# Step 14 — 100K correctness across compute-thread counts (1/2/4).
#
# The BUILD is skipped (GATE14_SKIP_BUILD=1) and the fixed, verified step2 100K
# graph is reused (hashes already confirmed == a fresh 1-thread rebuild), so the
# ONLY varying factor is the compute-region thread count. This is required
# because the build phase is not deterministic across thread counts.
#
# Because multithreaded output ORDER changes, every run's pairs are compared as
# an exact MULTISET: each pairs file is sorted and its sha256 + line multiset is
# compared across 1/2/4 threads and against the frozen step2 reference.
#
# Core sets are NESTED physical cores on NUMA node 0:
#   1 thread  -> {2}
#   2 threads -> {2,3}
#   4 threads -> {2,3,4,5}
# (CPU K and K+12 are SMT siblings; 2/3/4/5 are distinct physical cores.)
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step14_cpu_scaling"
BIN="$R/build/main"
FB="$ROOT/../gate5a/data/bigann100k.fbin"
G="$ROOT/runs/step2_100k/normal"          # fixed verified graph (read-only use)
REF="$G/pairs.txt"
D="$R/correctness_100k"
mkdir -p "$D"

echo "=== step14 100K correctness START $(date -Is) ===" | tee -a "$R/logs/driver.log"

run_t() { # $1 = threads, $2 = cpu list
  local t="$1" cpus="$2" dd="$D/t$1"
  mkdir -p "$dd"
  cat > "$dd/config" <<EOF
data_file $FB
radius 73984
cluster_num 1000
cluster_file $G/data.clusters
metadata_file $G/data.metadata
hnsw_file $G/data.hnsw
K 24
mem_budget 0.00476837158203125
error_bound 0.1
gt 3
EOF
  echo "=== [100K t=$t cpus=$cpus] START $(date -Is) ===" | tee -a "$R/logs/driver.log"
  taskset -c "$cpus" env OMP_NUM_THREADS="$t" OMP_PROC_BIND=true OMP_PLACES=cores \
    OMP_DISPLAY_AFFINITY=TRUE \
    GATE14_SKIP_BUILD=1 GATE13_C_PATH=1 GATE4B0_WINDOW=2 \
    GATE3_PAIR_OUT="$dd/pairs.txt" GATE4A_STATS=1 GATE3_INVARIANTS=1 \
    GATE4B1_IO_STATS=1 GATE4A_TASK_OUT="$dd/tasks.txt" GATE5B_PROFILE=1 GATE14_EXACT_COUNT=1 \
    /usr/bin/time -v timeout 600 "$BIN" "$dd/config" \
    > "$dd/stdout.log" 2> "$dd/stderr.log"
  echo "$?" > "$dd/rc.txt"
  echo "=== [100K t=$t] END $(date -Is) rc=$(cat "$dd/rc.txt") ===" | tee -a "$R/logs/driver.log"
}

run_t 1 "2"
run_t 2 "2,3"
run_t 4 "2,3,4,5"

echo "--- per-run threads + counts ---"
for t in 1 2 4; do
  dd="$D/t$t"
  echo "[t=$t] rc=$(cat $dd/rc.txt)"
  grep -hE '\[gate3\] pair_dump|\[gate3-stat\]|gate3-inv' "$dd/stderr.log"
  grep -h 'threads=' "$dd/stdout.log"
done

echo "--- sort pairs (exact multiset) + sha256 ---"
for t in 1 2 4; do
  LC_ALL=C sort "$D/t$t/pairs.txt" > "$D/t$t/pairs.sorted"
  sha256sum "$D/t$t/pairs.sorted" | tee -a "$D/sorted_hashes.txt"
done
LC_ALL=C sort "$REF" > "$D/ref_pairs.sorted"
sha256sum "$D/ref_pairs.sorted" | tee -a "$D/sorted_hashes.txt"

echo "--- exact multiset comparison (cmp on sorted files) ---"
if cmp -s "$D/t1/pairs.sorted" "$D/t2/pairs.sorted"; then echo "t1 vs t2: IDENTICAL"; else echo "t1 vs t2: DIFFER"; fi
if cmp -s "$D/t1/pairs.sorted" "$D/t4/pairs.sorted"; then echo "t1 vs t4: IDENTICAL"; else echo "t1 vs t4: DIFFER"; fi
if cmp -s "$D/t1/pairs.sorted" "$D/ref_pairs.sorted"; then echo "t1 vs ref: IDENTICAL"; else echo "t1 vs ref: DIFFER"; fi
for t in 1 2 4; do
  if cmp -s "$D/t$t/pairs.sorted" "$D/ref_pairs.sorted"; then echo "t$t vs ref: IDENTICAL"; else echo "t$t vs ref: DIFFER"; fi
done
echo "--- task hash across threads ---"
sha256sum "$D"/t*/tasks.txt
echo "=== step14 100K correctness END $(date -Is) ===" | tee -a "$R/logs/driver.log"
