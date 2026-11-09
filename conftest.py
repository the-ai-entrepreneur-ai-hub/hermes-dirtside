"""Load the read-only core checkout and isolate all test state."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE = os.environ.get("HERMES_SRC", str(ROOT.parent / "hermes-agent-main"))
sys.path.insert(0, CORE)
sys.path.append(str(ROOT / "tools"))
_test_home = tempfile.TemporaryDirectory(prefix="dirtside-tests-")
TEST_HOME = Path(_test_home.name).resolve()
for name in ("home", "tmp", "runtime"):
    (TEST_HOME / name).mkdir(parents=True, exist_ok=True)
os.environ.update(
    HERMES_HOME=str(TEST_HOME),
    HERMES_RUNTIME_DIR=str(TEST_HOME / "runtime"),
    HOME=str(TEST_HOME / "home"),
    TMPDIR=str(TEST_HOME / "tmp"),
    TERMINAL_TEMP_DIR=str(TEST_HOME / "tmp"),
    PYTHONDONTWRITEBYTECODE="1",
)
sys.dont_write_bytecode = True
tempfile.tempdir = str(TEST_HOME / "tmp")
