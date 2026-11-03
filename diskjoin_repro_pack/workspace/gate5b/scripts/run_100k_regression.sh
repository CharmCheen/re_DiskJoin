#!/bin/bash
# Gate 5B Step 2 bounded 100K output-consistency regression.
#
# Builds the PATCHED gate5b source in two configurations (normal + safe
# prefetch-off) and runs the deterministic 100K DiskJoin join with the exact
# same algorithm config as the frozen Gate 5A-R baseline, then checks that the
# output artifacts are byte-identical to the frozen baseline and that pairs are
# legal/unique. This is an OUTPUT-CONSISTENCY regression only; it makes no
# performance or physical-I/O claim.
#
# Bounded: OMP_NUM_THREADS=1 (single join thread), BUILD_JOBS<=4, per-step
# timeout 600 s, global 30-minute deadline, refuses to overwrite a run dir.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)          # workspace/gate5b
PACK=$(cd "$ROOT/.." && pwd)                     # workspace
DATA="$PACK/gate5a/data"
BVEC="$DATA/bigann100k.bvecs"
FBIN="$DATA/bigann100k.fbin"
BASE="$PACK/gate5a/runs/r1_default"              # frozen Gate 5A baseline
BASELINE_CFG="$PACK/gate5ar/runs/server_run_20261103_1138/normal/config"
SRC="$ROOT/instrumented/DiskJoin"
OUTBASE="$ROOT/runs/step2_100k"

export OMP_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1
JOBS=${BUILD_JOBS:-4}
case "$JOBS" in 1|2|3|4) ;; *) echo 'BUILD_JOBS must be 1..4' >&2; exit 2;; esac

test -f "$BVEC"; test -f "$FBIN"
for f in knn.txt tasks.txt pairs.txt trace.txt; do test -f "$BASE/$f"; done
test ! -e "$OUTBASE" || { echo "Run exists: refusing overwrite $OUTBASE" >&2; exit 2; }
mkdir -p "$OUTBASE"

DEADLINE=$((SECONDS + 1800))
run() { # label timeout cmd...
  local label=$1; shift
  local limit=$((DEADLINE - SECONDS))
  [ "$limit" -gt 0 ] || { echo '30-minute deadline reached' >&2; exit 124; }
  [ "$limit" -le 600 ] || limit=600
  echo "### [$label] timeout=${limit}s : $*"
  timeout "$limit" /usr/bin/time -v -o "$OUTBASE/${label}.time" "$@" \
      > "$OUTBASE/${label}.stdout" 2> "$OUTBASE/${label}.stderr"
  echo "### [$label] rc=$?"
}

echo "=== input hashes (gate5a 100K) ==="
sha256sum "$BVEC" "$FBIN" | tee "$OUTBASE/input_sha256.txt"

# Baseline config values (gt = diagnostic gt for vector 0) — read, not hardcoded.
GT=$(awk '$1=="gt"{print $2}' "$BASELINE_CFG")

for mode in normal prefetch_off; do
  flags=''
  [ "$mode" != prefetch_off ] || flags='-DGATE5AR_DISABLE_PREFETCH'
  BLD="$ROOT/build_100k_$mode"
  run "cmake_$mode" cmake -S "$SRC" -B "$BLD" "-DCMAKE_CXX_FLAGS=$flags"
  run "build_$mode" cmake --build "$BLD" --parallel "$JOBS"
  RD="$OUTBASE/$mode"; mkdir -p "$RD"
  cat > "$RD/config" <<EOF
data_file $FBIN
radius 73984
cluster_num 1000
cluster_file $RD/data.clusters
metadata_file $RD/data.metadata
hnsw_file $RD/data.hnsw
K 24
mem_budget 0.00476837158203125
error_bound 0.1
gt $GT
EOF
  limit=$((DEADLINE - SECONDS)); [ "$limit" -gt 0 ] || exit 124; [ "$limit" -le 600 ] || limit=600
  echo "### [join_$mode] timeout=${limit}s"
  timeout "$limit" /usr/bin/time -v -o "$RD/time.log" env \
    GATE4A_KNN_OUT="$RD/knn.txt" GATE4A_TASK_OUT="$RD/tasks.txt" \
    GATE3_PAIR_OUT="$RD/pairs.txt" GATE4A_CACHE_TRACE="$RD/trace.txt" \
    GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
    "$BLD/main" "$RD/config" > "$RD/stdout.log" 2> "$RD/stderr.log"
  echo "### [join_$mode] rc=$?"
done

echo
echo "=== artifact SHA-256: gate5b(normal) vs gate5b(prefetch_off) vs frozen baseline ==="
python3 -B "$ROOT/scripts/regression_compare.py" "$OUTBASE" "$BASE"
