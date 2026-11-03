#!/bin/bash
# Gate 4B-1 run wrapper.
#
# Correctness mode (default): all env-gated instrumentation dumps enabled
# (knn/tasks/pairs/trace + stats), OMP_NUM_THREADS=1, timeout 600 s.
# Timing mode (MODE=timing): NO instrumentation dumps (clean execution path),
# wall/CPU via /usr/bin/time -v, REP repeats (default 1).
#
# Usage: run_gate4b1.sh <name> <config> [VAR=value ...]
#   BIN=/path/to/main overrides the binary (e.g. build/asan/main).
set -uo pipefail
NAME=$1; CONFIG=$2; shift 2
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate4b1
BIN=${BIN:-$ROOT/build/normal/main}
MODE=${MODE:-correctness}
OUT=$ROOT/runs/$NAME
mkdir -p "$OUT"
export OMP_NUM_THREADS=1
if [ "$MODE" = "timing" ]; then
    REP=${REP:-1}
    for r in $(seq 1 "$REP"); do
        env "$@" timeout 600 /usr/bin/time -v -o "$OUT/time_r$r.log" \
            "$BIN" "$CONFIG" > "$ROOT/logs/${NAME}_r${r}.stdout" 2> "$ROOT/logs/${NAME}_r${r}.stderr"
        rc=$?
        echo "run $NAME (timing) rep$r rc=$rc"
        if [ $rc -ne 0 ]; then exit $rc; fi
    done
    exit 0
fi
rm -f "$OUT/knn.txt"   # GATE4A_KNN_OUT opens with std::ios::app
export GATE4A_KNN_OUT="$OUT/knn.txt"
export GATE4A_TASK_OUT="$OUT/tasks.txt"
export GATE3_PAIR_OUT="$OUT/pairs.txt"
export GATE4A_CACHE_TRACE="$OUT/trace.txt"
export GATE4A_STATS=1
export GATE3_INVARIANTS=1
export GATE4B1_IO_STATS=1
env "$@" timeout 600 "$BIN" "$CONFIG" > "$ROOT/logs/$NAME.stdout" 2> "$ROOT/logs/$NAME.stderr"
rc=$?
echo "run $NAME rc=$rc"
exit $rc
