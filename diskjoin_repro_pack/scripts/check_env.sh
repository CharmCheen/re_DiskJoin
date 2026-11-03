#!/usr/bin/env bash
# Read-only checks. No installs, downloads, edits, or benchmarking.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "DiskJoin minimal reproduction: environment audit"
printf 'Kernel: '; uname -sr
printf 'Machine: '; uname -m
for exe in git g++ cmake python3 curl; do
  if command -v "$exe" >/dev/null; then
    printf 'OK   %-12s %s\n' "$exe" "$(command -v "$exe")"
  else
    printf 'MISS %-12s\n' "$exe"
  fi
done
printf '\nMemory:\n'; (free -h || true) 2>/dev/null
printf '\nFilesystem available in pack directory:\n'; df -h "$ROOT" || true
if [[ -r /proc/cpuinfo ]]; then
  for flag in avx2 fma; do
    if grep -qw "$flag" /proc/cpuinfo; then echo "CPU flag $flag: present";
    else echo "CPU flag $flag: MISSING (reference uses native AVX2/FMA)"; fi
  done
fi
if [[ "$(uname -s)" != 'Linux' ]]; then
    echo 'WARNING: reference uses Linux-specific O_DIRECT. Use a Linux host.'
fi
printf '\nNote: CPU memory capacity and filesystem support for O_DIRECT matter; GPU is not required.\n'
