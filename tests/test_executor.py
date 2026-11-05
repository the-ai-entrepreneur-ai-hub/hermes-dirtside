"""Device policy, output and process-group execution contracts."""
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import psutil
import pytest

from dirtside.agent import executor
from dirtside.agent.executor import _Output, _read, run
from dirtside.agent.policy import evaluate
from dirtside.model import CHUNK_BYTES, FLUSH_MS, MAX_OUTPUT_BYTES, Policy, Refused, RequestState
from dirtside.protocol import WireExec

POLICY = Policy((), 900, MAX_OUTPUT_BYTES, 4)
PYTHON = shlex.quote(sys.executable)


def execute(root, script, *, policy=POLICY, timeout=120, stdin=None, command=None, cancel=None):
    chunks = []
    req = WireExec("r_" + "01" * 12, command or script, script, False, timeout, stdin, str(root))
    out, tail = run(req, policy, lambda seq, data: chunks.append((seq, data)) or True, cancel=cancel)
    if tail:
        chunks.append((tail.seq, tail.data))
    assert [seq for seq, _ in chunks] == list(range(len(chunks)))
    return out, b"".join(data for _, data in chunks)


def alive(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def await_file(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        threading.Event().wait(0.01)
    raise AssertionError(f"process did not create {path.name}")


@pytest.mark.parametrize("command,denied", [
    ("pwd", False), ("sudo id", True), ("echo safe", False), ("rm -rf /", True),
])
def test_policy_table(command, denied):
    policy = Policy((re.compile(r"\bsudo\b"), re.compile(r"rm -rf /")), 900, MAX_OUTPUT_BYTES, 4)
    assert isinstance(evaluate(command, policy), Refused) is denied


def test_policy_uses_command_not_wrapper(tmp_path):
    policy = Policy((re.compile("/dev/null"),), 900, MAX_OUTPUT_BYTES, 4)
    out, data = execute(tmp_path, "echo hi >/dev/null; echo ok", policy=policy, command="echo ok")
    assert out.exit_code == 0 and data == b"ok\n"
    out, data = execute(tmp_path, "touch should-not-exist", policy=policy, command="/dev/null")
    assert out.state is RequestState.REFUSED and out.exit_code == 126 and data == b""
    assert not (tmp_path / "should-not-exist").exists()


def test_async_stdin(tmp_path):
    payload = "地" * 400000
    script = f"{PYTHON} -c 'import sys; sys.stdout.write(\"x\" * 200000); sys.stdout.flush(); sys.stdout.buffer.write(sys.stdin.buffer.read())'"
    out, data = execute(tmp_path, script, stdin=payload)
    assert out.exit_code == 0
    assert data == b"x" * 200000 + payload.encode()


def test_flush_clock_boundaries_and_exit_tail(tmp_path, monkeypatch):
    clock, sent = [0.0], []
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    req = WireExec("r_" + "02" * 12, "printf early", "printf early", False, 120, None, str(tmp_path))
    output = _Output(req, POLICY, lambda seq, data: sent.append((seq, data)) or True)
    output.add(b"early")
    clock[0] = (FLUSH_MS - 1) / 1000
    assert output.flush(False) and sent == []
    clock[0] = FLUSH_MS / 1000
    assert output.flush(False) and sent == [(0, b"early")]
    output.add(b"late")
    clock[0] += 1
    assert output.flush(True) and sent == [(0, b"early")]
    assert output.tail().seq == 1 and output.tail().data == b"late"


def test_clock_and_size_flush(tmp_path):
    sent = []
    script = "printf early; while [ ! -e flushed ]; do sleep 0.01; done; printf late"
    req = WireExec("r_" + "02" * 12, script, script, False, 10, None, str(tmp_path))
    def send(seq, data):
        sent.append((seq, data))
        (tmp_path / "flushed").touch()
        return True
    out, tail = run(req, POLICY, send)
    assert out.exit_code == 0 and tail.data == b"late"
    assert sent == [(0, b"early")]
    out, data = execute(tmp_path, f"{PYTHON} -c 'import sys; sys.stdout.buffer.write(b\"x\" * {CHUNK_BYTES * 3})'")
    assert data == b"x" * (CHUNK_BYTES * 3) and not out.truncated


def test_short_output_inline(tmp_path):
    req = WireExec("r_" + "03" * 12, "echo hi", "echo hi", False, 120, None, str(tmp_path))
    sent = []
    out, tail = run(req, POLICY, lambda seq, data: sent.append(data) or True)
    assert out.exit_code == 0 and tail.data == b"hi\n" and sent == []


def test_output_cap(tmp_path):
    policy = Policy((), 900, 1000, 4)
    out, data = execute(tmp_path, f"{PYTHON} -c 'print(\"x\" * 200000)'", policy=policy)
    assert len(data) == 1000 and out.truncated and out.exit_code == 0
    assert "1000 bytes" in out.reason


def test_timeout_identity_survives_output_cap(tmp_path):
    policy = Policy((), 1, 1000, 4)
    out, data = execute(tmp_path, f"{PYTHON} -c 'print(\"x\" * 200000)'; sleep 60", policy=policy)
    assert data == b"x" * 1000 and out.exit_code == 124 and out.truncated
    assert out.reason == "command timed out; output capped at 1000 bytes on the device"


def test_timeout_kills_group(tmp_path):
    pidfile = tmp_path / "pid"
    out, data = execute(tmp_path, "echo $$ > pid; printf before; sleep 60",
                        policy=Policy((), 1, MAX_OUTPUT_BYTES, 4))
    assert out.exit_code == 124 and data == b"before"
    assert not alive(int(pidfile.read_text()))


def test_cancel_reaps_term_obeying_child_promptly(tmp_path):
    cancel = threading.Event()
    script = f"exec {PYTHON} -c 'import os,time; open(\"pid\", \"w\").write(str(os.getpid())); time.sleep(60)'"
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(execute, tmp_path, script, cancel=cancel)
        pid = int(await_file(tmp_path / "pid"))
        try:
            start = time.monotonic()
            cancel.set()
            out, _ = future.result(timeout=0.75)
            assert out.exit_code == 130 and time.monotonic() - start < 0.75
            assert not psutil.pid_exists(pid)
        finally:
            cancel.set()
            if alive(pid):
                os.kill(pid, 9)


def test_cancel_kills_term_ignoring_child(tmp_path):
    cancel = threading.Event()
    script = f"echo $$ > parent.pid; {PYTHON} -c 'import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(\"pid\", \"w\").write(str(os.getpid())); time.sleep(60)' & wait"
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(execute, tmp_path, script, cancel=cancel)
        pid = int(await_file(tmp_path / "pid"))
        assert os.getpgid(pid) == int(await_file(tmp_path / "parent.pid"))
        start = time.monotonic()
        cancel.set()
        out, _ = future.result(timeout=5)
    assert out.exit_code == 130 and time.monotonic() - start < 5
    try:
        while alive(pid) and time.monotonic() < start + 5:
            threading.Event().wait(0.01)
        assert not alive(pid)
    finally:
        if alive(pid):
            os.kill(pid, 9)


def test_rejected_post_kills_group(tmp_path):
    script = f"echo $$ > pid; {PYTHON} -c 'print(\"x\" * {CHUNK_BYTES * 2})'; sleep 60"
    req = WireExec("r_" + "04" * 12, script, script, False, 120, None, str(tmp_path))
    out, _ = run(req, POLICY, lambda seq, data: False)
    assert out.exit_code == 130 and not alive(int((tmp_path / "pid").read_text()))


def test_closed_stdout_still_observes_timeout(tmp_path):
    out, _ = execute(tmp_path, "exec 1>&- 2>&-; sleep 60", timeout=1)
    assert out.exit_code == 124


def test_eof_wait_is_bounded_until_process_exits():
    class Closing:
        def wait(self, timeout):
            assert timeout == 0.01
            raise subprocess.TimeoutExpired("closing-child", timeout)
    assert _read(Closing(), type("Output", (), {"eof": True})(), 0) == 3


def test_invalid_cwd_is_reported(tmp_path):
    out, _ = execute(tmp_path / "missing", "pwd")
    assert out.exit_code == 126 and "No such file" in out.reason


def test_natural_grandchild(tmp_path):
    start = time.monotonic()
    out, data = execute(tmp_path, "sleep 30 & echo $!")
    pid = int(data)
    try:
        assert out.exit_code == 0 and time.monotonic() - start < 1
        assert alive(pid)
    finally:
        if alive(pid):
            os.kill(pid, 15)


def test_already_cancelled_does_not_spawn(tmp_path):
    cancel = threading.Event()
    cancel.set()
    out, data = execute(tmp_path, "touch should-not-exist", cancel=cancel)
    assert out.exit_code == 130 and data == b""
    assert not (tmp_path / "should-not-exist").exists()
