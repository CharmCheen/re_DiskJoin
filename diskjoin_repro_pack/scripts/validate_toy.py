#!/usr/bin/env python3
"""Validate the generated fbin header and reference config before using the binary."""
import json
import struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'workspace/toy'
p=out/'toy.fbin'
meta=json.loads((out/'toy_metadata.json').read_text())
with p.open('rb') as f:
    n,d=struct.unpack('<II',f.read(8))
assert n==meta['n'] and d==meta['dimension'], 'header mismatch'
assert p.stat().st_size==8+n*d*4,'fbin size mismatch'
conf={}
for line in (out/'toy.config').read_text().splitlines():
    a,b=line.split(maxsplit=1)
    conf[a]=b
assert len(conf)==10, 'reference parser expects 10 ordered fields'
assert conf['data_file']==str(p) and Path(conf['data_file']).is_file()
assert int(conf['gt'])==meta['gt_sampled']>0
assert int(conf['cluster_num'])<=n and int(conf['K'])<=int(conf['cluster_num'])
print(f"Toy data checked: n={n}, d={d}, sampled_gt={meta['gt_sampled']}")
