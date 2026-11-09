"""Check descriptor ownership after every test and report the suite's counts."""
import json
import os
from pathlib import Path

import pytest

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


def pytest_terminal_summary(terminalreporter):
    if _fd_records:
        leaks = sum(row["delta"] > FD_MARGIN for row in _fd_records)
        terminalreporter.write_line(
            f"FD guard: {len(_fd_records)} tests, {leaks} leaks above margin {FD_MARGIN}; "
            f"start={_fd_records[0]['before']}, end={_fd_records[-1]['after']}, "
            f"peak_after={max(row['after'] for row in _fd_records)}"
        )
