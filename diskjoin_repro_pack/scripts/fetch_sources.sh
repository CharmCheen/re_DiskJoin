#!/usr/bin/env bash
# Deliberately opt-in: requires network on the user's machine.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHA="aa86151f97527b1dcf9a032d523c1d67d892454a"
REPO="$ROOT/reference/DiskJoin"
PAPER="$ROOT/paper/DiskJoin_arXiv_2508.18494v2.pdf"

command -v git >/dev/null || { echo "ERROR: git missing" >&2; exit 2; }
if [[ -d "$REPO/.git" ]]; then
    ACTUAL="$(git -C "$REPO" rev-parse HEAD)"
    if [[ "$ACTUAL" != "$SHA" ]]; then
        echo "ERROR: existing reference clone at unexpected commit: $ACTUAL" >&2
        echo "Do not replace it automatically. Inspect and move it manually if desired." >&2
        exit 3
    fi
    echo "REFERENCE VERIFIED: $ACTUAL"
elif [[ -e "$REPO" ]]; then
    echo "ERROR: $REPO exists but is not a git repository; will not overwrite" >&2
    exit 3
else
    echo "Fetching read-only reference from GitHub (pinned)..."
    git clone https://github.com/iidyc/DiskJoin.git "$REPO"
    git -C "$REPO" checkout --detach "$SHA"
    ACTUAL="$(git -C "$REPO" rev-parse HEAD)"
    [[ "$ACTUAL" == "$SHA" ]] || { echo "Git SHA mismatch" >&2; exit 4; }
    echo "REFERENCE VERIFIED: $ACTUAL"
fi

if [[ -f "$PAPER" ]]; then
    head -c 4 "$PAPER" | grep -q '%PDF' || { echo "Invalid existing PDF: $PAPER" >&2; exit 5; }
    echo "PAPER VERIFIED: $PAPER"
else
    command -v curl >/dev/null || { echo "ERROR: curl missing; download paper manually" >&2; exit 2; }
    echo "Downloading unmodified arXiv v2 PDF; ACM final is NOT fetched by this script."
    tmp="$(mktemp "$ROOT/paper/.diskjoin-pdf.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    curl --fail --location --retry 2 --connect-timeout 15 \
      'https://arxiv.org/pdf/2508.18494v2' --output "$tmp"
    head -c 4 "$tmp" | grep -q '%PDF' || { echo "Downloaded file is not a PDF" >&2; exit 5; }
    mv "$tmp" "$PAPER"
    trap - EXIT
    echo "PAPER DOWNLOADED: $PAPER"
fi
printf '\nREFERENCE SHA: %s\n' "$SHA"
printf 'ACM VoR: https://doi.org/10.1145/3769780\n'
