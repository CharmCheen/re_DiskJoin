#!/bin/bash
# Explicitly invoked server-only validation; no downloads, installation or old outputs.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo 'Requires native Linux x86_64 AVX2/FMA; no server run started.' >&2; exit 2
fi
if [ "$#" -ne 3 ]; then echo 'Usage: bash run_linux.sh EXISTING.bvecs EXISTING.fbin NEW_RUN_NAME' >&2; exit 2; fi
case "$3" in ''|*[!A-Za-z0-9_-]*) echo 'Invalid run name' >&2; exit 2;; esac
for tool in python3 g++ cmake timeout; do command -v "$tool" >/dev/null; done
test -x /usr/bin/time
grep -qw avx2 /proc/cpuinfo; grep -qw fma /proc/cpuinfo
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1
export UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
# Prior shell instrumentation/ablation settings must not leak into this run.
while IFS='=' read -r name value; do
  case "$name" in GATE3_*|GATE4A_*|GATE4B0_*|GATE4B1_*) unset "$name";; esac
done < <(env)
JOBS=${BUILD_JOBS:-4}
case "$JOBS" in 1|2|3|4) ;; *) echo 'BUILD_JOBS must be 1..4' >&2; exit 2;; esac
BVEC=$(realpath "$1"); FBIN=$(realpath "$2")
test -f "$BVEC"; test -f "$FBIN"
BASELINE_DIR=${BASELINE_DIR:-"$ROOT/../gate5a/runs/r1_default"}
for file in knn.txt tasks.txt pairs.txt trace.txt; do test -f "$BASELINE_DIR/$file"; done
OUT="$ROOT/runs/$3"
DEADLINE=$((SECONDS + 1800))
test ! -e "$OUT" || { echo 'Run exists: refusing overwrite' >&2; exit 2; }
python3 -B - "$ROOT" <<'PY'
import shutil,sys
from pathlib import Path
if shutil.disk_usage(sys.argv[1]).free < 2*1024**3: raise SystemExit('need >=2 GiB free disk')
mem = next(int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
if mem < 2*1024**3: raise SystemExit('need >=2 GiB available RAM')
PY
mkdir -p "$ROOT/runs"
mkdir "$OUT"
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "STOP rc=$rc; preserve $OUT" >&2; fi' EXIT
run () { # All long subprocesses have a 600-second wall limit and a time/RSS log.
  local label=$1; shift
  local limit=$((DEADLINE - SECONDS))
  [ "$limit" -gt 0 ] || { echo '30-minute validation deadline reached' >&2; exit 124; }
  [ "$limit" -le 600 ] || limit=600
  timeout "$limit" /usr/bin/time -v -o "$OUT/${label}.time" "$@" > "$OUT/${label}.stdout" 2> "$OUT/${label}.stderr"
}
python3 -B - "$BVEC" "$FBIN" "$OUT" <<'PY'
import hashlib,json,platform,sys
from pathlib import Path
expected=['cd48bfd0f8d8b86a179a36fde4f838ebdffaa79f7f12acbfee28f057acce69c3','d967109732b708dd054c2d1289203159ebae88b9bc46004a54961466816e16e1']
hashes={}
for name,want in zip(sys.argv[1:3],expected):
 digest=hashlib.sha256(Path(name).read_bytes()).hexdigest()
 if digest!=want: raise SystemExit('BigANN100K input hash mismatch: '+name)
 hashes[name]=digest
Path(sys.argv[3],'inputs.json').write_text(json.dumps(dict(platform=platform.platform(),sha256=hashes),indent=2)+'\n')
PY
python3 -B - "$ROOT" "$OUT" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
files=[p for sub in ['instrumented','oracle','scripts','tests'] for p in (root/sub).rglob('*') if p.is_file()]
Path(sys.argv[2],'source_sha256.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2)+'\n')
PY
run units python3 -B -m unittest discover -s "$ROOT/tests" -v
run oracle_build g++ -std=c++11 -O3 -fopenmp "$ROOT/oracle/gt_calib.cpp" -o "$OUT/gt_calib"
python3 -B "$ROOT/oracle/sample_endpoints.py" --out "$OUT/split"
run calibration env OMP_NUM_THREADS=4 "$OUT/gt_calib" calib "$BVEC" "$OUT/split/calibration.txt"
# Keep m=272 fixed to isolate the correctness repair; calibration is diagnostic.
run gt "$OUT/gt_calib" gt "$BVEC" "$OUT/split/evaluation.txt" 272 "$OUT/gt.txt"
run diagnostic "$OUT/gt_calib" gt "$BVEC" "$OUT/split/diagnostic.txt" 272 "$OUT/diagnostic.txt"
run independent python3 -B "$ROOT/oracle/independent_check.py" "$BVEC" "$FBIN" "$OUT/gt.txt" "$OUT/diagnostic.txt"
for mode in normal asan prefetch_off; do
  flags=''
  [ "$mode" != asan ] || flags='-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all'
  [ "$mode" != prefetch_off ] || flags='-DGATE5AR_DISABLE_PREFETCH'
  run "cmake_$mode" cmake -S "$ROOT/instrumented/DiskJoin" -B "$OUT/build_$mode" "-DCMAKE_CXX_FLAGS=$flags"
  run "build_$mode" cmake --build "$OUT/build_$mode" --parallel "$JOBS"
  run "hnsw_build_$mode" g++ -std=c++11 -O1 -g -mavx2 -mfma -pthread $flags \
    -I "$ROOT/instrumented/DiskJoin/lib/hnswlib" "$ROOT/tests/hnsw_regression.cpp" -o "$OUT/hnsw_$mode"
  run "hnsw_$mode" "$OUT/hnsw_$mode"
  mkdir "$OUT/$mode"
  python3 -B - "$OUT/$mode" "$FBIN" "$OUT/diagnostic.txt" <<'PY'
import sys
from pathlib import Path
r=Path(sys.argv[1]);gt=int(Path(sys.argv[3]).read_text().split()[1])
if gt==0: raise SystemExit('vector 0 has zero GT: stop, in-binary denominator undefined')
items=[('data_file',sys.argv[2]),('radius',73984),('cluster_num',1000),('cluster_file',r/'data.clusters'),('metadata_file',r/'data.metadata'),('hnsw_file',r/'data.hnsw'),('K',24),('mem_budget','0.00476837158203125'),('error_bound',0.1),('gt',gt)]
(r/'config').write_text(''.join(f'{k} {v}\n' for k,v in items))
PY
  limit=$((DEADLINE - SECONDS))
  [ "$limit" -gt 0 ] || exit 124
  [ "$limit" -le 600 ] || limit=600
  timeout "$limit" /usr/bin/time -v -o "$OUT/$mode/time.log" env \
    GATE4A_KNN_OUT="$OUT/$mode/knn.txt" GATE4A_TASK_OUT="$OUT/$mode/tasks.txt" \
    GATE3_PAIR_OUT="$OUT/$mode/pairs.txt" GATE4A_CACHE_TRACE="$OUT/$mode/trace.txt" \
    GATE4A_STATS=1 GATE3_INVARIANTS=1 GATE4B1_IO_STATS=1 \
    "$OUT/build_$mode/main" "$OUT/$mode/config" > "$OUT/$mode/stdout.log" 2> "$OUT/$mode/stderr.log"
  run "compare_$mode" python3 -B "$ROOT/scripts/validate_run.py" "$OUT" --baseline "$BASELINE_DIR" --through-mode "$mode"
done
run evaluation python3 -B "$ROOT/oracle/evaluate.py" --gt "$OUT/gt.txt" --diagnostic-gt "$OUT/diagnostic.txt" \
  --split "$OUT/split" --pairs "$OUT/normal/pairs.txt" --out "$OUT/evaluation.json"
python3 -B - "$OUT/inputs.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
for name,want in json.loads(Path(sys.argv[1]).read_text())['sha256'].items():
 if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=want: raise SystemExit('input changed: '+name)
PY
echo "Bounded correctness validation completed: $OUT. Performance and physical SSD I/O remain UNVERIFIED."
