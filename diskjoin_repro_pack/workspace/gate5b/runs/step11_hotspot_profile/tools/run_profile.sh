#!/usr/bin/env bash
# Step 11 — single fixed-config phase-timing run (the ONLY run this round).
#
# Reuses the step10 10% configuration exactly, except:
#   * binary  = runs/step11_hotspot_profile/build/main (GATE5B_PROFILE patch)
#   * graph   = rebuilt into runs/step11_hotspot_profile/graph (fresh dir, so
#               step10's evidential graph is NOT overwritten)
#   * GATE5B_PROFILE=1 (env-gated coarse phase timers; no logic change)
# Held fixed vs step10 r02_b010: BigANN1M fbin, mem_budget 0.0476837158203125
# (10%), radius 73984, cluster_num 1000, K 24, error_bound 0.1, gt 8379,
# GATE4B0_WINDOW=2 (actual Gorder window = 2), OMP_NUM_THREADS=1, taskset -c 2,
# pair/trace output OFF (GATE3_COUNT_ONLY), all existing counters ON.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step11_hotspot_profile"
BIN="$R/build/main"
CPU="${PIN_CPU:-2}"
FBPATH="$ROOT/acq1m/data/bigann1m.fbin"
D="$R/runs/profile_10pct"
mkdir -p "$D" "$R/graph" "$R/logs"

cat > "$D/config" <<EOF
data_file $FBPATH
radius 73984
cluster_num 1000
cluster_file $R/graph/data.clusters
metadata_file $R/graph/data.metadata
hnsw_file $R/graph/data.hnsw
K 24
mem_budget 0.0476837158203125
error_bound 0.1
gt 8379
EOF

echo "=== PROFILE START $(date -Is) cpu=$CPU ===" | tee -a "$R/logs/driver.log"
: > "$D/monitor.log"; touch "$D/.mon"
( while [ -f "$D/.mon" ]; do
    rss=$(ps -C main -o rss= 2>/dev/null | awk '{a+=$1}END{print a+0}')
    disk=$(du -sb "$R" 2>/dev/null | cut -f1)
    ld=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null)
    printf '%s rss_kb=%s step11_disk_bytes=%s load=%s\n' "$(date +%s)" "$rss" "$disk" "$ld" >> "$D/monitor.log"
    sleep 10
  done ) &
MON=$!

taskset -c "$CPU" env OMP_NUM_THREADS=1 GATE4B0_WINDOW=2 \
  GATE3_PAIR_OUT="$D/count_sink_unused" GATE3_COUNT_ONLY=1 \
  GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
  GATE4A_TASK_OUT="$D/tasks.txt" GATE5B_PROFILE=1 \
  /usr/bin/time -v timeout 1500 "$BIN" "$D/config" \
  > "$D/stdout.log" 2> "$D/stderr.log"
RC=$?
rm -f "$D/.mon"; wait "$MON" 2>/dev/null
echo "$RC" > "$D/rc.txt"
sha256sum "$R/graph/data.clusters" "$R/graph/data.metadata" "$R/graph/data.hnsw" "$D/tasks.txt" > "$D/hashes.txt"
grep -hE 'gate[0-9]|recall|s\]' "$D/stdout.log" "$D/stderr.log" > "$D/gates.txt"
echo "=== PROFILE END $(date -Is) rc=$RC ===" | tee -a "$R/logs/driver.log"
echo "--- rc=$RC ---"
cat "$D/stdout.log"
grep -hE 'gate5b-prof|gate4a-|gate3|count_only|recall' "$D/stderr.log" "$D/stdout.log"
grep -iE 'Elapsed|Maximum resident|Percent of CPU' "$D/stderr.log"
sha256sum "$D/config"
cat "$D/hashes.txt"
