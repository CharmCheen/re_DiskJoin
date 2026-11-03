#!/bin/bash
# Gate 4B-1 timing runs (MODE=timing: NO instrumentation dumps, wall/CPU via
# /usr/bin/time -v). REP=1 for all 36 matrix configs; REP=5 for the five key
# configs used for repeat measurement (p1/p3 gorder/reject/eb01, p3
# identity/reject/eb01, p1/p3 gorder/lru/eb01).
# NOTE: runs include the full build phase (deterministic rebuild) each time;
# Build/Join split comes from the binary's own timer ticks in stdout,
# wall/CPU from the time logs. Sub-second differences are NOT performance
# claims (see report: no SSD-speedup claims from these).
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate4b1
cd "$ROOT"
run_one () { # name ds order policy eb rep
  local name=$1 ds=$2 order=$3 policy=$4 eb=$5 rep=$6
  local cfg=data/${ds}_small_g4b1.config
  [ "$eb" = "10" ] && cfg=data/${ds}_eb1.0_small_g4b1.config
  local envs="GATE4B1_POLICY=$policy GATE4B1_CAPACITY=62 GATE4B0_WINDOW=4"
  case "$order" in
    identity) envs="$envs GATE4B0_ORDER=identity" ;;
    random)   envs="$envs GATE4B0_ORDER=file GATE4B0_PERM_FILE=data/perm_random_seed20260101.txt" ;;
  esac
  # shellcheck disable=SC2086
  MODE=timing REP=$rep ./oracle/run_gate4b1.sh "t_$name" "$cfg" $envs || echo "TIMING FAILED: t_$name"
}
for ds in p1 p3; do
  for order in gorder identity random; do
    for policy in belady_reject belady_forced lru_forced; do
      for eb in 01 10; do
        rep=1
        case "${ds}_${order}_${policy}_eb${eb}" in
          p1_gorder_belady_reject_eb01|p3_gorder_belady_reject_eb01|\
          p3_identity_belady_reject_eb01|p3_gorder_lru_forced_eb01|\
          p1_gorder_lru_forced_eb01) rep=5 ;;
        esac
        run_one "${ds}_${order}_${policy}_eb${eb}" "$ds" "$order" "$policy" "$eb" "$rep"
      done
    done
  done
done
