#!/usr/bin/env bash
# Step 13 — ASan+UBSan 100K join with the C path enabled, output compared to the
# frozen step2 100K normal pairs. This exercises the fixed-128 C path through the
# real join (same/cross bucket, tails, empty buckets) under sanitizers.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step13_c_integration"
BIN="$R/asan_build/main"
FB="$ROOT/../gate5a/data/bigann100k.fbin"
G="$R/asan_100k"; mkdir -p "$G"
REF="$ROOT/runs/step2_100k/normal/pairs.txt"

cat > "$G/config" <<EOF
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

echo "=== asan 100k START $(date -Is) ===" | tee -a "$R/logs/driver.log"
taskset -c "${PIN_CPU:-2}" env OMP_NUM_THREADS=1 GATE4B0_WINDOW=2 GATE13_C_PATH=1 \
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
  UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  GATE3_PAIR_OUT="$G/pairs.txt" GATE3_PAIR_STREAM=1 \
  GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
  GATE4A_TASK_OUT="$G/tasks.txt" \
  /usr/bin/time -v timeout 900 "$BIN" "$G/config" > "$G/stdout.log" 2> "$G/stderr.log"
echo "rc=$?" | tee -a "$G/rc.txt"

echo "--- sanitizer hits ---"
grep -cE 'AddressSanitizer|LeakSanitizer|runtime error:|ERROR:' "$G/stdout.log" "$G/stderr.log"
echo "--- counters ---"
grep -hE 'gate3-stat|gate3\]|gate3-inv|gate4a-cache|gate4b1-io|recall' "$G/stdout.log" "$G/stderr.log"
echo "--- pairs cmp vs step2 100k normal ---"
sha256sum "$G/pairs.txt" "$REF"
if cmp "$G/pairs.txt" "$REF"; then echo "CMP=IDENTICAL"; else echo "CMP=DIFFER"; fi | tee "$G/cmp.txt"
