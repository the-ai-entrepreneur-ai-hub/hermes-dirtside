"""Compare output, status and cwd against core local execution on the same host."""
import os
import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from network_support import until
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.interrupt import set_interrupt
from tools.process_registry import ProcessRegistry

from dirtside.environment import DirtsideEnvironment
from test_environment import device_setup
from test_executor import alive, await_file
from client_support import client_relay


@pytest.fixture(params=["in-process", "client"])
def remote_environment(request):
    with ExitStack() as stack:
        def create(relay, device):
            transport = stack.enter_context(client_relay(relay)) if request.param == "client" else relay
            return DirtsideEnvironment(transport, device, "chat", "default", "~", 120)
        yield create


def compare(local, remote, command, **kwargs):
    left, right = local.execute(command, **kwargs), remote.execute(command, **kwargs)
    assert right["output"] == left["output"]
    assert right["returncode"] == left["returncode"]
    assert remote.cwd == local.cwd
    return right


@pytest.mark.parametrize("commands", [
    ["pwd"],
    ["cd 'cwd with spaces'", "pwd"],
    ["export X=1", "echo $X"],
    ["exit 3"],
    ["nosuchcommand"],
    ["echo a; echo b >&2; echo c"],
    [f"{shlex.quote(sys.executable)} -c 'print(\"地\" * 70000, end=\"\")'"],
    ["seq 1 160000"],
    ["cd does-not-exist"],
])
def test_conformance(tmp_path, commands, remote_environment):
    (tmp_path / "cwd with spaces").mkdir()
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            for command in commands:
                compare(local, remote, command)
            remote.cleanup()
    finally:
        local.cleanup()


def test_conformance_random_bytes(tmp_path, remote_environment):
    source = tmp_path / "random.bin"
    source.write_bytes(os.urandom(100000))
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            result = compare(local, remote, f"head -c 100000 {shlex.quote(str(source))} | base64")
            assert len(result["output"]) > 133000
    finally:
        local.cleanup()


def test_conformance_timeout(tmp_path, remote_environment):
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            result = compare(local, remote, "printf partial; sleep 5", timeout=1)
            assert result["returncode"] == 124 and "partial" in result["output"]
            assert result["hermes_timed_out"] is True
    finally:
        local.cleanup()


def test_conformance_missing_cwd(tmp_path, remote_environment):
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            result = compare(local, remote, "pwd", cwd=str(tmp_path / "does-not-exist"))
            assert result["returncode"] == 126
            assert "does-not-exist" in result["output"]
            assert remote.cwd == str(tmp_path)
    finally:
        local.cleanup()


def test_conformance_file_operations(tmp_path, remote_environment):
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            payload = "alpha\n" + "abcdef地\n" * 100000 + "tail"
            path = str(tmp_path / "document.txt")
            results = []
            for env in (local, remote):
                ops = ShellFileOperations(env)
                written = ops.write_file(path, payload)
                assert not written.error and written.verified
                read = ops.read_file_raw(path)
                assert not read.error and read.content == payload
                patched = ops.patch_replace(path, "alpha", "beta")
                assert patched.success and not patched.error
                assert ops.read_file_raw(path).content == payload.replace("alpha", "beta", 1)
                files = ops.search("*.txt", str(tmp_path), target="files")
                matches = ops.search("^beta$", path)
                assert not files.error and not matches.error
                results.append((written.bytes_written, read.content, patched.diff, files, matches))
            assert results[0] == results[1]
            assert local.cwd == remote.cwd
    finally:
        local.cleanup()


def test_conformance_grandchild(tmp_path, remote_environment):
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            for env in (local, remote):
                start = time.monotonic()
                result = env.execute("sleep 30 & echo $! > child.pid")
                pid = int((tmp_path / "child.pid").read_text())
                try:
                    assert result["output"] == "" and result["returncode"] == 0
                    assert time.monotonic() - start < 1 and alive(pid)
                    assert env.cwd == str(tmp_path)
                finally:
                    if alive(pid):
                        os.kill(pid, 15)
    finally:
        local.cleanup()


def test_conformance_stop(tmp_path, remote_environment):
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    results = []
    try:
        with fake:
            remote = remote_environment(relay, device)
            for index, env in enumerate((local, remote)):
                ids = []

                def execute():
                    ids.append(threading.get_ident())
                    try:
                        return env.execute(f"printf partial; echo $$ > stop-{index}.pid; sleep 60")
                    finally:
                        set_interrupt(False)

                with ThreadPoolExecutor(1) as pool:
                    future = pool.submit(execute)
                    pid = int(await_file(tmp_path / f"stop-{index}.pid"))
                    if env is remote:
                        until(lambda: any(relay.tail(rid) == b"partial" for rid in list(relay.handles)))
                    set_interrupt(True, ids[0])
                    result = future.result(timeout=1)
                assert result["returncode"] == 130
                results.append((result["output"], result["returncode"], env.cwd))
                deadline = time.monotonic() + 5
                while alive(pid) and time.monotonic() < deadline:
                    threading.Event().wait(0.05)
                assert not alive(pid)
            assert results[0] == results[1]
    finally:
        local.cleanup()


def background(env, root):
    registry = ProcessRegistry()
    first = root / "background-first"
    second = root / "background-second"
    # Core can detect exit after reading a delta, without a final log read.
    command = (
        'for part in first second; do printf %s "$part"; '
        f'while [ ! -e {shlex.quote(str(root))}/background-"$part" ]; do sleep 0.01; done; done; exit 7'
    )
    session = registry.spawn_via_env(env, command)
    deadline = time.monotonic() + 30
    statuses = []
    saw_delta = False
    try:
        while time.monotonic() < deadline:
            status = registry.poll(session.id)
            statuses.append(status)
            saw_delta |= status["output_preview"] == "first"
            if saw_delta:
                first.touch()
            if status["output_preview"] == "firstsecond":
                second.touch()
            if status["status"] == "exited":
                break
            threading.Event().wait(0.05)
        assert statuses[-1]["status"] == "exited" and len(statuses) >= 2 and saw_delta
        assert statuses[-1]["exit_code"] == 7
        assert registry.read_log(session.id)["output"] == "firstsecond"
        return statuses[-1]["output_preview"], statuses[-1]["exit_code"], env.cwd
    finally:
        if not session.exited:
            registry.kill_process(session.id)
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)


def test_spawn_via_env(tmp_path, remote_environment):
    relay, device, fake = device_setup(tmp_path)
    local = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        with fake:
            remote = remote_environment(relay, device)
            assert background(local, tmp_path) == background(remote, tmp_path)
    finally:
        local.cleanup()
