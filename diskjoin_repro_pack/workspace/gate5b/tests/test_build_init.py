"""Lightweight regression guard for the clean-checkout `build/` init defect.

Gate 5A-R server run server_run_20261103_1134 aborted at its first step
(`units`) because `scripts/run_linux.sh` did not create the gitignored
scratch directory `workspace/gate5ar/build/`, while `tests/test_correctness.py`
uses `tempfile.TemporaryDirectory(dir=ROOT / "build")`.  `scripts/run_local.sh`
already performed the equivalent `mkdir -p "$ROOT/build" "$ROOT/logs"`.

These tests do not touch the dataset, the network or the join pipeline; they
only assert that the Linux entry script self-initialises the scratch dir before
it invokes the unit-test suite, and that the command it uses actually works
when the directory is absent.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "scripts" / "run_linux.sh"
LOCAL = ROOT / "scripts" / "run_local.sh"

MKDIR_BUILD = 'mkdir -p "$ROOT/build"'


class BuildDirInitRegression(unittest.TestCase):
    def test_run_linux_creates_build_dir_before_units(self):
        script = LINUX.read_text()
        self.assertRegex(
            script, r'mkdir\s+-p\s+"\$ROOT/build"',
            'run_linux.sh must create the scratch build dir',
        )
        # It must be created before the unit-test suite that needs it.
        self.assertLess(
            script.index(MKDIR_BUILD), script.index("python3 -B -m unittest"),
            'build dir must be created before `units` runs',
        )

    def test_run_local_still_initialises_scratch(self):
        # Preserve the sibling script's behaviour the Linux fix mirrors.
        self.assertRegex(LOCAL.read_text(), r'mkdir\s+-p\s+"\$ROOT/build"')

    def test_missing_build_dir_is_recoverable(self):
        # Behavioural: the exact command used by run_linux.sh turns an absent
        # scratch dir into a usable one (the scenario of run ..._1134).
        with tempfile.TemporaryDirectory() as sandbox:
            fake_root = Path(sandbox) / "root"
            fake_root.mkdir()
            build = fake_root / "build"
            self.assertFalse(build.exists())
            subprocess.run(
                ["bash", "-c", 'ROOT="$1"; mkdir -p "$ROOT/build"', "bash", str(fake_root)],
                check=True,
            )
            self.assertTrue(build.is_dir())
            with tempfile.TemporaryDirectory(dir=build):
                pass


if __name__ == "__main__":
    unittest.main()
