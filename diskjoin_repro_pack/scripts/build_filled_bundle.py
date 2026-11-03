#!/usr/bin/env python3
"""After fetching sources on user's machine, make a private, source-filled archive.

This is opt-in. Keep output private to respect third-party code / paper rights.
"""
import hashlib
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT/'reference/DiskJoin'
PAPER=ROOT/'paper/DiskJoin_arXiv_2508.18494v2.pdf'
SHA='aa86151f97527b1dcf9a032d523c1d67d892454a'
if not (REPO/'lib/DiskJoin.h').is_file():
    raise SystemExit('Reference source missing: run bash scripts/fetch_sources.sh first')
if not (REPO/'.git/HEAD').exists():
    raise SystemExit('Reference .git missing; refuse to pretend SHA verified')
import subprocess
head=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
if head!=SHA:
    raise SystemExit(f'Reference at unexpected commit {head}, expected {SHA}')
if not PAPER.is_file() or PAPER.read_bytes()[:4]!=b'%PDF':
    raise SystemExit('arXiv PDF missing/invalid: run bash scripts/fetch_sources.sh first')
output=ROOT.parent/'DiskJoin_Private_Filled_Offline_Bundle.zip'
if output.exists():
    raise SystemExit(f'Refusing to overwrite existing archive: {output}')
count=0
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as z:
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file(): continue
        rel=p.relative_to(ROOT)
        if 'workspace' in rel.parts or '__pycache__' in rel.parts: continue
        if '.git' in rel.parts: continue  # preserve source tree content but not internal Git storage
        z.write(p, arcname='diskjoin_repro_pack/'+rel.as_posix())
        count+=1
print(f'Created private archive {output} ({count} files, sha256={hashlib.sha256(output.read_bytes()).hexdigest()})')
print('Note: this package excludes upstream .git internals; SHA is evidenced by repo.lock / local verification, not independently verifiable inside archive.')
print('For local/private academic use; inspect reference repository rights before redistribution.')
