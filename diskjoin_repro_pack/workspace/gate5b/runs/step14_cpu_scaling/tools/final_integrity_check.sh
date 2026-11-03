#!/usr/bin/env bash
# Step 14 final integrity check (run after the perf suite completes).
set -u
cd /home/qch/DiskJoin/diskjoin_repro_pack/workspace/gate5b
R=runs/step14_cpu_scaling

echo "=== 1M per-run counts (must all be equal) ==="
for d in "$R"/perf/r*; do
  printf "%s rc=%s " "$(basename "$d")" "$(cat "$d/rc.txt" 2>/dev/null)"
  grep -hoE 'pairs=[0-9]+ threads=[0-9]+' "$d/stderr.log" | head -1
  grep -hoE 'sampled_count=[0-9]+' "$d/stderr.log"
  grep -hoE 'dist_comp_exact=[0-9]+' "$d/stderr.log"
  grep -hoE 'recall = [0-9.]+' "$d/stdout.log"
done

echo; echo "=== distinct exact counts / pairs / sampled (should be 1 each) ==="
for k in 'dist_comp_exact=[0-9]+' 'pairs=[0-9]+' 'sampled_count=[0-9]+'; do
  printf "%-22s distinct=" "$k"
  grep -hoE "$k" "$R"/perf/r*/stderr.log | sort -u | tr '\n' ' '; echo
done

echo; echo "=== sanitizer/error strings (must be none) ==="
grep -lE 'AddressSanitizer|runtime error|ERROR' "$R"/perf/r*/stderr.log 2>/dev/null || echo "none"

echo; echo "=== affinity per run ==="
for d in "$R"/perf/r*; do
  printf "%s: " "$(basename "$d")"
  grep -hoE 'affinity [0-9]+' "$d/stderr.log" | awk '{printf "%s ",$2}'; echo
done

echo; echo "=== step14 disk ==="; du -sh "$R"; du -sb "$R" | awk '{printf "%.3f GiB (cap 2.0)\n",$1/1073741824}'
echo "=== git HEAD unchanged / nothing committed ==="; git rev-parse HEAD
echo "=== old evidence untouched (newer than 17:25:00)? ==="
find runs/step7_1m_normal runs/step8_1m_prefetch_off runs/step9_1m_dedup runs/step10_cache_sensitivity runs/step11_hotspot_profile runs/step12_compute_replay runs/step13_c_integration -newermt '2026-11-03 17:25:00' -type f 2>/dev/null | head
echo "(empty above = untouched)"
echo "now $(date -Is)"
