#!/bin/bash
# Gate 4B-1 main experiment matrix (pre-registered, 36 runs):
#   datasets {p1, p3}
#   x task order {gorder (default), identity, random (seed 20260101, frozen perm file)}
#   x cache policy {belady_reject, belady_forced, lru_forced}
#   x error_bound {0.1, 1.0}
# Pinned in EVERY run: OMP_NUM_THREADS=1 (wrapper), GATE4B1_CAPACITY=62,
# GATE4B0_WINDOW=4, frozen bucketization (rebuilt clusters/metadata/hnsw must
# stay byte-identical to gate4a), same GT protocol. Correctness mode: all
# instrumentation dumps (knn/tasks/pairs/trace) + stats.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate4b1
cd "$ROOT"
fail=0
for ds in p1 p3; do
  for order in gorder identity random; do
    for policy in belady_reject belady_forced lru_forced; do
      for eb in 01 10; do
        name=${ds}_${order}_${policy}_eb${eb}
        cfg=data/${ds}_small_g4b1.config
        [ "$eb" = "10" ] && cfg=data/${ds}_eb1.0_small_g4b1.config
        envs="GATE4B1_POLICY=$policy GATE4B1_CAPACITY=62 GATE4B0_WINDOW=4"
        case "$order" in
          identity) envs="$envs GATE4B0_ORDER=identity" ;;
          random)   envs="$envs GATE4B0_ORDER=file GATE4B0_PERM_FILE=data/perm_random_seed20260101.txt" ;;
        esac
        # shellcheck disable=SC2086
        ./oracle/run_gate4b1.sh "$name" "$cfg" $envs || { echo "MATRIX FAILED: $name rc=$?"; fail=1; }
      done
    done
  done
done
exit $fail
