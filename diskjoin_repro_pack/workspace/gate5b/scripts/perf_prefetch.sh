#!/bin/bash
# Gate 5A-R BigANN100K bounded PREFETCH performance pre-check.
# Compares the SAFE prefetch build (default) against the prefetch-disabled build
# (-DGATE5AR_DISABLE_PREFETCH). The known-UB historical build is never used.
# Fixed: dataset, graph, task order, threshold, cache budget, CPU affinity,
# thread count and measurement window. Large diagnostic dumps are disabled;
# only the cheap counters are kept. Total budget 15 minutes.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo 'Requires native Linux x86_64 AVX2/FMA; no measurement started.' >&2; exit 2
fi
if [ "$#" -ne 3 ]; then echo 'Usage: bash perf_prefetch.sh EXISTING.fbin NEW_RUN_NAME JOBS' >&2; exit 2; fi
case "$2" in ''|*[!A-Za-z0-9_-]*) echo 'Invalid run name' >&2; exit 2;; esac
JOBS=${3:-4}
case "$JOBS" in 1|2|3|4) ;; *) echo 'JOBS must be 1..4' >&2; exit 2;; esac
for tool in python3 g++ cmake timeout taskset; do command -v "$tool" >/dev/null; done
test -x /usr/bin/time
grep -qw avx2 /proc/cpuinfo; grep -qw fma /proc/cpuinfo
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
FBIN=$(realpath "$1"); test -f "$FBIN"
OUT="$ROOT/runs/$2"
DEADLINE=$((SECONDS + 900))         # 15-minute total budget
test ! -e "$OUT" || { echo 'Run exists: refusing overwrite' >&2; exit 2; }
mkdir -p "$ROOT/build" "$OUT"
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "PERF-STOP rc=$rc; preserve $OUT" >&2; fi' EXIT

budget () { [ "$((DEADLINE - SECONDS))" -gt 0 ] || { echo '15-minute perf deadline reached' >&2; exit 124; }; }
# Long subprocess: per-step 600 s cap, GNU time + RSS log.
timed () { local label=$1; shift; local limit=$((DEADLINE - SECONDS));
  [ "$limit" -gt 0 ] || exit 124; [ "$limit" -le 600 ] || limit=600
  timeout "$limit" /usr/bin/time -v -o "$OUT/${label}.time" "$@" > "$OUT/${label}.stdout" 2> "$OUT/${label}.stderr"; }

# ---- environment record (measurement conditions) -------------------------
{
  echo "date=$(date -Is)"
  echo "host=$(uname -n) kernel=$(uname -r)"
  echo "cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | xargs)"
  echo "nproc=$(nproc) affinity=taskset -c 0-3 OMP_NUM_THREADS=1"
  echo "fbin=$FBIN sha256=$(sha256sum "$FBIN" | cut -d' ' -f1)"
  echo "note=page cache not droppable without privilege; bucket reads use O_DIRECT; runs alternate to spread cache state"
} > "$OUT/environment.txt"

# ---- builds ---------------------------------------------------------------
budget
timed cmake_safe cmake -S "$ROOT/instrumented/DiskJoin" -B "$OUT/build_safe" "-DCMAKE_CXX_FLAGS="
timed build_safe cmake --build "$OUT/build_safe" --parallel "$JOBS"
budget
timed cmake_off cmake -S "$ROOT/instrumented/DiskJoin" -B "$OUT/build_off" "-DCMAKE_CXX_FLAGS=-DGATE5AR_DISABLE_PREFETCH"
timed build_off cmake --build "$OUT/build_off" --parallel "$JOBS"
SAFE_BIN="$OUT/build_safe/main"; OFF_BIN="$OUT/build_off/main"
test -x "$SAFE_BIN"; test -x "$OFF_BIN"

# ---- fixed graph/threshold/cache config, one dir per run ------------------
make_config () { # $1 = run dir
  local r=$1
  cat > "$r/config" <<EOF
data_file $FBIN
radius 73984
cluster_num 1000
cluster_file $r/data.clusters
metadata_file $r/data.metadata
hnsw_file $r/data.hnsw
K 24
mem_budget 0.00476837158203125
error_bound 0.1
gt 3
EOF
}

run_one () { # $1=dir $2=binary
  local r=$1 bin=$2
  mkdir -p "$r"; make_config "$r"
  budget
  local limit=$((DEADLINE - SECONDS)); [ "$limit" -le 600 ] || limit=600
  # diagnostics OFF (no *_OUT); cheap counters ON; pinned affinity/threads.
  timeout "$limit" /usr/bin/time -v -o "$r/time.log" env \
    OMP_NUM_THREADS=1 GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
    taskset -c 0-3 "$bin" "$r/config" > "$r/stdout.log" 2> "$r/stderr.log"
}

# warmup (discarded from summary; recorded anyway) to reduce cold-cache bias
echo '[perf] warmup (safe), discarded from summary'
run_one "$OUT/warmup_safe" "$SAFE_BIN"

for i in 1 2 3; do
  echo "[perf] round $i: safe then prefetch_off"
  run_one "$OUT/run${i}_safe" "$SAFE_BIN"
  run_one "$OUT/run${i}_off"  "$OFF_BIN"
done

# ---- verification: outputs/counters identical across all runs -------------
budget
python3 -B - "$OUT" <<'PY'
import hashlib, json, re, sys
from pathlib import Path
out = Path(sys.argv[1])
runs = [f"run{i}_{m}" for i in range(1,4) for m in ("safe","off")]
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()
def parse(rd):
    err=(rd/"stderr.log").read_text(); so=(rd/"stdout.log").read_text(); tl=(rd/"time.log").read_text()
    def g(pat,s=err): 
        m=re.search(pat,s); return m.group(1) if m else None
    rec=dict(
      elapsed=g(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*(\S+)",tl),
      rss_kb=g(r"Maximum resident set size \(kbytes\):\s*(\d+)",tl),
      fs_inputs=g(r"File system inputs:\s*(\d+)",tl),
      fs_outputs=g(r"File system outputs:\s*(\d+)",tl),
      build_s=g(r"\[([0-9.]+) s\] Build done",so),
      join_s=g(r"\[([0-9.]+) s\] Join done",so),
      recall=g(r"recall = ([0-9.]+)",so),
      task_num=g(r"task_num_total=(\d+)"),
      dist_comp=g(r"dist_comp=(\d+)"),
      miss=g(r"miss=(\d+)"), hit=g(r"hit=(\d+)"),
      capacity_slots=g(r"capacity_slots=(\d+)"), budget_bytes=g(r"budget_bytes=(\d+)"),
      read_calls=g(r"read_calls=(\d+)"), effective_bytes=g(r"effective_bytes=(\d+)"),
      requested_aligned_bytes=g(r"requested_aligned_bytes=(\d+)"),
      perm_ok=g(r"perm_ok=(\d+)"), upper_triangle_ok=g(r"upper_triangle_ok=(\d+)"),
      bucket_sum=g(r"bucket_sum=(\d+)"),
    )
    rec["sha"]={n:sha(rd/n) for n in ("data.clusters","data.metadata","data.hnsw")}
    return rec
data={r:parse(out/r) for r in runs}
ref=data[runs[0]]
incons={}
for r in runs:
    for k in ("recall","task_num","dist_comp","miss","hit","capacity_slots","budget_bytes",
              "read_calls","effective_bytes","requested_aligned_bytes","bucket_sum"):
        if data[r][k]!=ref[k]: incons.setdefault(k,[]).append((r,data[r][k]))
    for n,h in data[r]["sha"].items():
        if h!=ref["sha"][n]: incons.setdefault("sha:"+n,[]).append((r,h))
print("all runs consistent:", not incons)
if incons:
    print("INCONSISTENCIES:", json.dumps(incons, indent=2))
    raise SystemExit("PERF-STOP: output/counter inconsistency")
(out/"perf_verify.txt").write_text("all runs consistent: True\nreference="+runs[0]+"\n")
(out/"perf_summary.json").write_text(json.dumps(data, indent=2)+"\n")
# quick table
print(f"{'run':14} {'build_s':>8} {'join_s':>8} {'wall':>9} {'rss_kb':>9} {'fs_in':>9} {'miss':>6} {'read_calls':>10}")
for r in runs:
    d=data[r]
    print(f"{r:14} {d['build_s']:>8} {d['join_s']:>8} {d['elapsed']:>9} {d['rss_kb']:>9} {d['fs_inputs']:>9} {d['miss']:>6} {d['read_calls']:>10}")
PY

echo "Bounded perf pre-check completed: $OUT. Physical SSD I/O remains UNVERIFIED."
