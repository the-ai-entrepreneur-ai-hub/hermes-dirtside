"""Load the read-only core checkout and isolate all test state."""

import os
import sqlite3
import sys
import tempfile
import threading
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent
CORE = os.environ.get("HERMES_SRC", str(ROOT.parent / "hermes-agent-main"))
sys.path.insert(0, CORE)
sys.path.append(str(ROOT / "tools"))
sys.path.append(str(ROOT / "tests"))
pytest_plugins = ["fd_guard"]
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

@pytest.fixture(autouse=True)
def core_lsp_service(descriptor_guard):
    yield
    if module := sys.modules.get("agent.lsp"):
        module.shutdown_service()


@pytest.fixture(autouse=True)
def registry_connections(descriptor_guard, monkeypatch):
    from dirtside import registry
    lock = threading.Lock()
    with ExitStack() as owned:
        def connect(*args, **kwargs):
            # Keep thread-local use; allow the fixture owner to close after worker shutdown.
            connection = sqlite3.connect(*args, **kwargs, check_same_thread=False)
            with lock:
                return owned.enter_context(closing(connection))
        monkeypatch.setattr(registry, "sqlite3", SimpleNamespace(connect=connect, Row=sqlite3.Row))
        yield
