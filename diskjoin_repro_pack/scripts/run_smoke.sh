#!/usr/bin/env bash
# Build and run ONLY the toy experiment. Never invokes scripts/run.sh (100M).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SHA="aa86151f97527b1dcf9a032d523c1d67d892454a"
REPO="$ROOT/reference/DiskJoin"
[[ -d "$REPO/.git" ]] || { echo "Missing reference repo; run bash scripts/fetch_sources.sh" >&2; exit 2; }
ACTUAL="$(git -C "$REPO" rev-parse HEAD)"
[[ "$ACTUAL" == "$SHA" ]] || { echo "Unpinned reference checkout $ACTUAL; stop" >&2; exit 2; }
[[ "$(uname -s)" == "Linux" ]] || { echo 'Linux required for O_DIRECT reference implementation' >&2; exit 2; }
command -v g++ >/dev/null && command -v cmake >/dev/null || { echo 'g++ and cmake required' >&2; exit 2; }

if [[ ! -e workspace/toy/toy.fbin ]]; then
  python3 scripts/make_toy.py
fi
python3 scripts/validate_toy.py
mkdir -p workspace/build workspace/runs
cmake -S "$REPO" -B workspace/build
cmake --build workspace/build -j "${BUILD_JOBS:-4}"
RUNDIR="$(mktemp -d "$ROOT/workspace/runs/toy-XXXXXX")"
printf '%s\n' "$SHA" > "$RUNDIR/reference_commit.txt"
cp workspace/toy/toy.config "$RUNDIR/config.snapshot"
echo "Run folder: $RUNDIR"
set +e
OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}" ./workspace/build/main "$ROOT/workspace/toy/toy.config" > "$RUNDIR/stdout.log" 2> "$RUNDIR/stderr.log"
rc=$?
set -e
cat "$RUNDIR/stdout.log"
if [[ "$rc" -ne 0 ]]; then
  echo "Reference failed with code $rc. See $RUNDIR/stderr.log" >&2
  exit "$rc"
fi
python3 scripts/parse_run.py --log "$RUNDIR/stdout.log" --metadata workspace/toy/toy_metadata.json --out "$RUNDIR/summary.json"
echo "Completed: $RUNDIR"
