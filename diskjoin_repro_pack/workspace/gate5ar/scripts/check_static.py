"""Source checks; no bytecode, generated files or prior-Gate writes."""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT.parents[1]
for path in ROOT.rglob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
for path in ROOT.rglob("*.sh"):
    subprocess.run(["bash", "-n", str(path)], check=True)
h = (ROOT / "instrumented/DiskJoin/lib/hnswlib/hnswalg.h").read_text()
assert h.count("_mm_prefetch") == 3, "all raw hints must be confined to checked prefetchNode"
helper = h[h.index("inline void prefetchNode"):h.index("int getRandomLevel")]
assert helper.count("_mm_prefetch") == 3
assert "*(datal + j + 1)" not in h and "*(data + j + 1)" not in h
assert "*(datal + i + 1)" not in h
before = json.loads((ROOT / "frozen_before.json").read_text())
changed = [name for name, digest in before.items()
           if not (PACK / name).is_file() or hashlib.sha256((PACK / name).read_bytes()).hexdigest() != digest]
assert not changed, f"frozen files changed: {changed}"
print(f"AST/Bash/prefetch checks PASS; {len(before)} prior files unchanged")
