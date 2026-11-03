#!/bin/bash
# Gate 4B-0 run wrapper: one full diskjoin build+search run with all
# env-gated instrumentation dumps enabled. OMP=1 (bit-deterministic),
# timeout 600s, all outputs under runs/<name>/, logs under logs/.
#
# Usage: run_gate4b0.sh <name> <config> [VAR=value ...]
#   BIN=/path/to/main can override the binary via environment.
set -uo pipefail
NAME=$1; CONFIG=$2; shift 2
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate4b0
BIN=${BIN:-$ROOT/build/normal/main}
OUT=$ROOT/runs/$NAME
mkdir -p "$OUT"
rm -f "$OUT/knn.txt"   # GATE4A_KNN_OUT opens with std::ios::app
export OMP_NUM_THREADS=1
export GATE4A_KNN_OUT="$OUT/knn.txt"
export GATE4A_TASK_OUT="$OUT/tasks.txt"
export GATE3_PAIR_OUT="$OUT/pairs.txt"
export GATE4A_CACHE_TRACE="$OUT/trace.txt"
export GATE4A_STATS=1
export GATE3_INVARIANTS=1
env "$@" timeout 600 "$BIN" "$CONFIG" > "$ROOT/logs/$NAME.stdout" 2> "$ROOT/logs/$NAME.stderr"
rc=$?
echo "run $NAME rc=$rc"
exit $rc
