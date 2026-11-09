"""Load the read-only core checkout and isolate all test state."""

import json
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

FD_MARGIN = 2  # Allow two bounded framework/startup descriptors, not SQLite's three-file WAL.
_fd_records = []


def _open_descriptors():
    directory = "/proc/self/fd" if Path("/proc/self/fd").is_dir() else "/dev/fd"
    opened = set()
    for name in os.listdir(directory):
        try:
            os.fstat(fd := int(name))
        except OSError:
            continue  # The directory iterator's own descriptor has already closed.
        opened.add(fd)
    return opened


@pytest.fixture(autouse=True)
def descriptor_guard(request):
    before = _open_descriptors()
    yield
    after = _open_descriptors()
    delta = len(after) - len(before)
    record = dict(nodeid=request.node.nodeid, before=len(before), after=len(after), delta=delta)
    _fd_records.append(record)
    if path := os.environ.get("DIRTSIDE_FD_LOG"):
        with Path(path).open("a") as log:
            log.write(json.dumps(record) + "\n")
    assert delta <= FD_MARGIN, (
        f"{request.node.nodeid} leaked {delta} descriptors "
        f"(before={len(before)}, after={len(after)}, margin={FD_MARGIN}, new={sorted(after - before)})"
    )


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


def pytest_terminal_summary(terminalreporter):
    if _fd_records:
        leaks = sum(row["delta"] > FD_MARGIN for row in _fd_records)
        terminalreporter.write_line(
            f"FD guard: {len(_fd_records)} tests, {leaks} leaks above margin {FD_MARGIN}; "
            f"start={_fd_records[0]['before']}, end={_fd_records[-1]['after']}, "
            f"peak_after={max(row['after'] for row in _fd_records)}"
        )
