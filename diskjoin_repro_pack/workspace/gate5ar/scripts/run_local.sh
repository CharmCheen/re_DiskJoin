#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$ROOT/build" "$ROOT/logs"
python3 -B -m unittest discover -s "$ROOT/tests" -v
python3 -B "$ROOT/scripts/check_static.py"
python3 -B "$ROOT/scripts/check_patches.py"
CXX=${CXX:-clang++}
"$CXX" -std=c++11 -O1 -g -DNO_MANUAL_VECTORIZATION \
  -fsanitize=address,undefined -fno-sanitize-recover=all \
  -I "$ROOT/instrumented/DiskJoin/lib/hnswlib" \
  "$ROOT/tests/hnsw_regression.cpp" -o "$ROOT/build/hnsw_scalar_sanitized"
"$ROOT/build/hnsw_scalar_sanitized"
echo 'Scalar sanitizer regression PASS. Linux SSE/AVX2/OpenMP/O_DIRECT remain unverified here.'
