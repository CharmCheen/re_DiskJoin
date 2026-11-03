"""Read-only patch validation; handles a reproduction pack nested in a Git repo."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT.parents[1]
repo = subprocess.check_output(["git", "-C", str(PACK), "rev-parse", "--show-toplevel"], text=True).strip()
prefix = PACK.relative_to(repo).as_posix()
prefix = "" if prefix == "." else prefix + "/"
checks = [("workspace/gate5a/instrumented/DiskJoin", "hnsw_safety.patch"),
          ("workspace/gate5a", "oracle_offset_and_validation.patch"),
          ("workspace/gate5a", "disjoint_sampling.patch"),
          ("workspace/source_snapshot/DiskJoin-aa86151f97527b1dcf9a032d523c1d67d892454a", "upstream_to_gate5ar.patch")]
for base, patch in checks:
    result = subprocess.run(["git", "-C", repo, "apply", "--check", "--verbose",
                             "--directory="+prefix+base, str(ROOT / "patches" / patch)],
                            capture_output=True, text=True)
    print(result.stdout + result.stderr, end="", flush=True)
    if result.returncode or "Skipped patch" in result.stderr or "Checking patch" not in result.stderr:
        raise SystemExit("FAILED: " + patch)
    print(patch + " PASS (checked; no skipped patch)", flush=True)
