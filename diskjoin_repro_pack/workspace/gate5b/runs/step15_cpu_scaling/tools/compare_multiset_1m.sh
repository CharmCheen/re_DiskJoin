#!/usr/bin/env bash
# Step 15 — exact multiset comparison: 4-thread GATE15 sink vs step7 1-thread ref.
#
# Both multisets are aggregated by tools/aggregate_multiset.sh, which sorts and
# streams the canonical ordered pair sequence to sha256 + N/U/duplicate counters.
# A matching sha256 over the full sorted byte stream is an exact multiset
# equality (not a count/XOR/sum surrogate). Sorts run sequentially, so only one
# sorted stream exists at a time; no full sorted file is retained.
set -u
ROOT=/home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R="$ROOT/runs/step15_cpu_scaling"
AGG="$R/tools/aggregate_multiset.sh"
C="$R/correctness_1m"
T="$R/tmp"
mkdir -p "$C" "$T"

echo "=== aggregate 4-thread GATE15 sink (sequential sort) $(date -Is) ==="
bash "$AGG" "$T" "t4" "$C/t4"/pairs.txt.t0 "$C/t4"/pairs.txt.t1 "$C/t4"/pairs.txt.t2 "$C/t4"/pairs.txt.t3

echo "=== aggregate step7 1-thread reference (sequential sort) $(date -Is) ==="
bash "$AGG" "$T" "ref" "$ROOT/runs/step7_1m_normal/pairs.txt"

echo "=== copy canonical aggregate records into correctness_1m ==="
for l in t4 ref; do
  cp "$T/$l.sha256" "$C/agg_$l.sha256"
  cp "$T/$l.stats"  "$C/agg_$l.stats"
  cp "$T/$l.rc"     "$C/agg_$l.rc"
  cp "$T/$l.sorterr" "$C/agg_$l.sorterr"
done

echo "=== comparison ==="
h4=$(cat "$T/t4.sha256"); hr=$(cat "$T/ref.sha256")
s4=$(cat "$T/t4.stats"); sr=$(cat "$T/ref.stats")
echo "t4 sorted sha256 = $h4"
echo "t4 stats         = $s4"
echo "ref sorted sha256= $hr"
echo "ref stats        = $sr"
echo "t4 agg rc  : $(grep -E 'sort_rc|sha256_rc' "$T/t4.rc" | tr '\n' ' ')"
echo "ref agg rc : $(grep -E 'sort_rc|sha256_rc' "$T/ref.rc" | tr '\n' ' ')"
rc4=$(sed -n 's/.*sort_rc=\([0-9]*\).*/\1/p' "$T/t4.rc" | head -1)
rcr=$(sed -n 's/.*sort_rc=\([0-9]*\).*/\1/p' "$T/ref.rc" | head -1)
echo "sort_rc: t4=$rc4 ref=$rcr"
# last-group settlement: N must equal the raw input line count, and (U==N here)
# means the final sorted group is a counted singleton, not dropped.
nsum=0
for f in "$C/t4"/pairs.txt.t*; do nsum=$((nsum + $(wc -l < "$f"))); done
echo "per-thread raw line sum = $nsum"
if [ "$h4" = "$hr" ] && [ -n "$h4" ] && [ "$rc4" = "0" ] && [ "$rcr" = "0" ]; then
  echo "RESULT: MULTISETS IDENTICAL (exact, full sorted-stream SHA256 match)"
  echo "MULTISETS IDENTICAL (sha256=$h4) t4_stats=[$s4] ref_stats=[$sr] per_thread_line_sum=$nsum" > "$C/COMPARISON_RESULT.txt"
else
  echo "RESULT: MULTISETS DIFFER — keep counterexample, do NOT freeze"
  echo "MULTISETS DIFFER t4=$h4 ref=$hr" > "$C/COMPARISON_RESULT.txt"
fi
