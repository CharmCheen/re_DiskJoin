#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests -v
python3 scripts/micro_task_cache.py
python3 scripts/validate_toy.py
