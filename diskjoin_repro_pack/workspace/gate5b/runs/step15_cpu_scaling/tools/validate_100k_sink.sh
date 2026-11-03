#!/usr/bin/env bash
# Step 15 — validate the GATE15 per-thread streaming sink on 100K (fast).
#
# Purpose: prove the new output-only sink does not change compute logic. Run
# 1-thread and 4-thread 100K joins with GATE15_PER_THREAD_STREAM, concatenate
# the per-thread files, and compare the exact pair MULTISET against (a) the
# frozen step2 100K reference and (b) each other. A gate that altered candidate
# generation/order/pruning/distance would change the multiset and fail here.
#
# Fixed: GATE14_SKIP_BUILD=1 (reuse verified step2 graph), GATE13_C_PATH=1,
# GATE4B0_WINDOW=2, same config as step14's 100K correctness run.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step15_cpu_scaling"
BIN="$R/build/main"
FB="$ROOT/../gate5a/data/bigann100k.fbin"
G="$ROOT/runs/step2_100k/normal"
REF="$G/pairs.txt"
D="$R/validate_100k"
mkdir -p "$D"

run_t() { # $1=threads $2=cpus
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
  echo "=== [val100k t=$t cpus=$cpus] START $(date -Is) ==="
  taskset -c "$cpus" env OMP_NUM_THREADS="$t" OMP_PROC_BIND=true OMP_PLACES=cores \
    GATE14_SKIP_BUILD=1 GATE13_C_PATH=1 GATE4B0_WINDOW=2 \
    GATE3_PAIR_OUT="$dd/pairs.txt" GATE15_PER_THREAD_STREAM=1 \
    GATE3_INVARIANTS=1 GATE14_EXACT_COUNT=1 \
    /usr/bin/time -v timeout 600 "$BIN" "$dd/config" \
    > "$dd/stdout.log" 2> "$dd/stderr.log"
  echo "$?" > "$dd/rc.txt"
  echo "=== [val100k t=$t] END rc=$(cat "$dd/rc.txt") $(date -Is) ==="
}

run_t 1 "2"
run_t 4 "2,3,4,5"

# concatenate per-thread files into one multiset raw file
for t in 1 4; do
  dd="$D/t$t"
  cat "$dd"/pairs.txt.t* > "$dd/pairs.concat" 2>/dev/null
  echo "[t=$t] per-thread files:"; ls -la "$dd"/pairs.txt.t* | awk '{print "   ",$5,$9}'
  echo "[t=$t] concat lines: $(wc -l < "$dd/pairs.concat")"
  grep -h '\[gate15\]' "$dd/stderr.log"
done

echo "--- exact multiset compare (sorted) ---"
LC_ALL=C sort "$D/t1/pairs.concat" > "$D/t1/pairs.sorted"
LC_ALL=C sort "$D/t4/pairs.concat" > "$D/t4/pairs.sorted"
LC_ALL=C sort "$REF"              > "$D/ref_pairs.sorted"
sha256sum "$D/t1/pairs.sorted" "$D/t4/pairs.sorted" "$D/ref_pairs.sorted" | tee "$D/sorted_hashes.txt"
for x in t1 t4; do
  if cmp -s "$D/$x/pairs.sorted" "$D/ref_pairs.sorted"; then echo "$x vs step2 ref: IDENTICAL"; else echo "$x vs step2 ref: DIFFER"; fi
done
if cmp -s "$D/t1/pairs.sorted" "$D/t4/pairs.sorted"; then echo "t1 vs t4: IDENTICAL"; else echo "t1 vs t4: DIFFER"; fi
echo "--- exact distance counts ---"
grep -h '\[gate14-exact\]' "$D"/t*/stderr.log
echo "--- rc ---"; for t in 1 4; do echo "t$t rc=$(cat "$D/t$t/rc.txt")"; done
