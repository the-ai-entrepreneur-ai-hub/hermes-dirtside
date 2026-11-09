"""Real high-descriptor streams and the suite's descriptor ownership guard."""
import asyncio
import json
import os
import resource
import struct
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from core_rig import Core, Rig

from dirtside.agent import executor
from dirtside.local import LocalAPI
from dirtside.protocol import WireExec
from test_executor import POLICY
from test_registry import request
from test_relay import FINISHED, setup_relay

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def high_descriptors():
    original = resource.getrlimit(resource.RLIMIT_NOFILE)
    soft, hard = original
    opened = []
    try:
        if soft != resource.RLIM_INFINITY and soft < 2048:
            raised = 2048 if hard == resource.RLIM_INFINITY else min(2048, hard)
            assert raised > 1150, "high-descriptor regression needs a hard limit above 1150"
            resource.setrlimit(resource.RLIMIT_NOFILE, (raised, hard))
        while not opened or opened[-1] < 1100:
            opened.append(os.open(os.devnull, os.O_RDONLY))
        yield
    finally:
        for fd in reversed(opened):
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, original)


def test_executor_runs_and_streams_above_select_ceiling(tmp_path, monkeypatch, high_descriptors):
    sent, pipes = [], []
    read = executor._read
    def observe(proc, *args):
        pipes.append(proc.stdout.fileno())
        return read(proc, *args)
    monkeypatch.setattr(executor, "_read", observe)
    script = "printf early; while [ ! -e flushed ]; do sleep 0.01; done; printf late"
    req = WireExec("r_" + "06" * 12, script, script, False, 10, None, str(tmp_path))
    def send(seq, data):
        sent.append((seq, data))
        (tmp_path / "flushed").touch()
        return True
    outcome, tail = executor.run(req, POLICY, send)
    assert pipes and min(pipes) > 1024
    assert outcome.exit_code == 0 and not outcome.truncated
    assert sent == [(0, b"early")] and tail.seq == 1 and tail.data == b"late"


def test_relay_writes_above_select_ceiling(tmp_path, high_descriptors):
    relay, device = setup_relay(tmp_path)
    with closing(relay.registry._connection()):
        handle = relay.submit(request(device))
        try:
            assert min(handle.stdout.fileno(), handle._write_fd) > 1024
            assert relay.feed(handle.req.id, 0, b"streamed")
            assert relay.close(handle.req.id, FINISHED)
            assert handle.stdout.read() == b"streamed" and handle.wait(0) == 0
        finally:
            handle.kill()
            handle.stdout.close()


def test_local_stream_reads_above_select_ceiling(tmp_path, high_descriptors):
    relay, device = setup_relay(tmp_path)
    with closing(relay.registry._connection()):
        handle = relay.submit(request(device))
        try:
            assert handle.stdout.fileno() > 1024
            os.write(handle._write_fd, b"streamed")
            relay.close(handle.req.id, FINISHED)
            async def consume():
                return b"".join([part async for part in LocalAPI(relay.registry, relay, lambda: True).output(handle)])
            wire = asyncio.run(consume())
            assert wire[:12] == struct.pack("!I", 8) + b"streamed"
            assert wire[12:16] == b"\0\0\0\0"
            assert json.loads(wire[16:])["exit_code"] == 0 and handle.stdout.closed
        finally:
            handle.kill()
            handle.stdout.close()


@pytest.mark.parametrize("leak", [False, True], ids=["closed", "leaked"])
def test_descriptor_guard_checks_actual_teardown(tmp_path, leak):
    source = tmp_path / "test_descriptor_owner.py"
    source.write_text(
        "import os\n"
        "def test_owned_descriptors():\n"
        "    descriptors = [os.open(os.devnull, os.O_RDONLY) for _ in range(4)]\n"
        + ("" if leak else "    for fd in descriptors:\n        os.close(fd)\n")
    )
    env = os.environ | {"DIRTSIDE_FD_LOG": str(tmp_path / "guard.jsonl")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "conftest", "--confcutdir=" + str(tmp_path),
         "--rootdir=" + str(tmp_path), str(source)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == int(leak), result.stdout + result.stderr
    assert ("leaked 4 descriptors" in result.stdout) is leak
    assert "FD guard: 1 tests" in result.stdout


def test_owned_core_closes_stdin_after_external_exit(tmp_path):
    core = Core(tmp_path / "core", worker=True)
    try:
        core.proc.kill()
        core.proc.wait(3)
        core.close()
        core.close()
        assert core.proc.stdin.closed and core.proc.stdout.closed and core.log.closed
    finally:
        core.close()
        core.proc.stdin.close()


def test_owned_agent_closes_stdin_after_external_exit(tmp_path):
    rig = object.__new__(Rig)
    rig.device_command = [sys.executable]
    rig.agent_log = (tmp_path / "agent.log").open("w")
    rig.agent = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.PIPE, stdout=rig.agent_log)
    try:
        rig.agent.wait(3)
        rig.stop_agent()
        rig.stop_agent()
        assert rig.agent.stdin.closed and rig.agent_log is None
    finally:
        rig.stop_agent()
        rig.agent.stdin.close()
