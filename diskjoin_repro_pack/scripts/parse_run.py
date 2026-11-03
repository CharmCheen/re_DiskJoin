#!/usr/bin/env python3
"""Parse reference output. This is a smoke-test validation, not a paper replication."""
import argparse
import json
import math
import re
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--log',required=True)
p.add_argument('--metadata',required=True)
p.add_argument('--out',required=True)
a=p.parse_args()
s=Path(a.log).read_text()
m=json.loads(Path(a.metadata).read_text())
match=re.findall(r'\brecall\s*=\s*([0-9.eE+-]+)',s)
if not match:raise SystemExit('FAIL: reference program printed no recall')
value=float(match[-1])
if not math.isfinite(value) or value<0 or value>1.00001:
    raise SystemExit(f'FAIL: invalid sampled recall {value}')
build = re.search(r'\[([0-9.]+) s\] Build done',s)
join = re.search(r'\[([0-9.]+) s\] Join done',s)
summary={'status':'PASS_SMOKE_ONLY','sampled_recall':value,'sampled_gt':m['gt_sampled'],
         'build_elapsed_seconds':float(build.group(1)) if build else None,
         'join_cumulative_elapsed_seconds':float(join.group(1)) if join else None,
         'warning':'Reference sampled recall uses IDs divisible by 100000. Not a full recall/quality proof.'}
Path(a.out).write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
