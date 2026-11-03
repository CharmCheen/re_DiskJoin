#!/usr/bin/env bash
# Step 15 — canonical multiset aggregation for one set of pair files.
#
# Sorts the input pair files (byte order, LC_ALL=C) and streams the SORTED
# bytes through (a) sha256sum and (b) an awk unique/duplicate counter, using a
# named FIFO so no full sorted file is ever written to disk. This keeps peak
# disk = raw inputs + sort's own spill temp, within the 16 GiB budget, while
# still producing a canonical ordered pair sequence whose SHA256 is an EXACT
# multiset identifier (full sequence, not a count/XOR/sum surrogate).
#
# Usage: aggregate_multiset.sh <outdir> <label> <input files...>
# Writes:  <outdir>/<label>.sha256, <label>.stats, <label>.rc, <label>.sorterr
set -u
outdir="$1"; label="$2"; shift 2
mkdir -p "$outdir"
fifo="$outdir/.${label}.fifo"
rm -f "$fifo"; mkfifo "$fifo"

# sha256 of the sorted stream, read from the FIFO
sha256sum < "$fifo" | awk '{print $1}' > "$outdir/$label.sha256" &
shpid=$!

set -o pipefail
LC_ALL=C sort -S 1G --parallel=3 -T "$outdir" "$@" 2> "$outdir/$label.sorterr" \
  | tee "$fifo" \
  | awk '
      { n++
        if (n==1) { prev=$0; u=1 }
        else if ($0==prev) { d++ }
        else { u++; prev=$0 }
      }
      END { printf "N=%d U=%d duplicates=%d\n", n, u, d }
    ' > "$outdir/$label.stats"

rcs=("${PIPESTATUS[@]}")
rc_sort=${rcs[0]:-1}
rc_tee=${rcs[1]:-1}
rc_awk=${rcs[2]:-1}
wait "$shpid"; rc_sha=$?
set +o pipefail
rm -f "$fifo"

{
  echo "label=$label"
  echo "inputs=$(printf '%s ' "$@")"
  echo "sort_rc=$rc_sort tee_rc=$rc_tee awk_rc=$rc_awk sha256_rc=$rc_sha"
  echo "sort_stderr_bytes=$(wc -c < "$outdir/$label.sorterr")"
  echo "sha256=$(cat "$outdir/$label.sha256")"
  cat "$outdir/$label.stats"
} | tee "$outdir/$label.rc"
