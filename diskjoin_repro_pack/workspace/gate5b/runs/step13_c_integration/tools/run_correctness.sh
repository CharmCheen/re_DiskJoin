#!/usr/bin/env bash
# Step 13 — 1M correctness run of the C path with streaming pair output.
#
# Runs the patched binary ONCE with GATE13_C_PATH=1 and the ORIGINAL streaming
# pair dump (GATE3_PAIR_STREAM=1, OMP_NUM_THREADS=1) into
# correctness/pairs.txt, then compares it byte-for-byte and by sha256 with the
# verified normal 1M output (runs/step7_1m_normal/pairs.txt). All other knobs
# are the fixed 10%-cache configuration, single thread, taskset -c 2.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step13_c_integration"
BIN="$R/build/main"
CPU="${PIN_CPU:-2}"
FB="$ROOT/acq1m/data/bigann1m.fbin"
G="$R/graph"; D="$R/correctness"
REF="$ROOT/runs/step7_1m_normal/pairs.txt"
REF_SHA="cfb4b9c0be815e52e938464865c51b94cefb29d1affe470dcad60e6d9685e69a"
mkdir -p "$G" "$D" "$R/logs"

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

: > "$D/monitor.log"; touch "$D/.mon"
( while [ -f "$D/.mon" ]; do
    rss=$(ps -C main -o rss= 2>/dev/null | awk '{a+=$1}END{print a+0}')
    printf '%s rss_kb=%s\n' "$(date +%s)" "$rss" >> "$D/monitor.log"
    sleep 10
  done ) &
MON=$!

echo "=== step13 correctness START $(date -Is) ===" | tee -a "$R/logs/driver.log"
taskset -c "$CPU" env OMP_NUM_THREADS=1 GATE4B0_WINDOW=2 \
  GATE13_C_PATH=1 \
  GATE3_PAIR_OUT="$D/pairs.txt" GATE3_PAIR_STREAM=1 \
  GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
  GATE4A_TASK_OUT="$D/tasks.txt" GATE5B_PROFILE=1 \
  /usr/bin/time -v timeout 1500 "$BIN" "$D/config" \
  > "$D/stdout.log" 2> "$D/stderr.log"
RC=$?
rm -f "$D/.mon"; wait "$MON" 2>/dev/null
echo "$RC" > "$D/rc.txt"
echo "=== step13 correctness END $(date -Is) rc=$RC ===" | tee -a "$R/logs/driver.log"

echo "--- gate counters (C run) ---"
grep -hE 'gate3-stat|gate3\]|gate3-inv|gate4a-cache|gate4b1-io|gate4a-config|recall' "$D/stdout.log" "$D/stderr.log"

echo "--- pairs size / lines ---"
ls -l "$D/pairs.txt"
wc -l "$D/pairs.txt" | tee "$D/pairs_lines.txt"

echo "--- sha256 (C run vs step7 reference) ---"
sha256sum "$D/pairs.txt" | tee "$D/pairs.sha256"
echo "reference sha256: $REF_SHA"

echo "--- byte-for-byte cmp vs step7 normal pairs ---"
if cmp "$D/pairs.txt" "$REF"; then echo "CMP=IDENTICAL"; else echo "CMP=DIFFER"; fi | tee "$D/cmp.txt"

echo "--- graph + task hashes (must match step7/step11) ---"
sha256sum "$G/data.clusters" "$G/data.metadata" "$G/data.hnsw" "$D/tasks.txt" | tee "$D/hashes.txt"
