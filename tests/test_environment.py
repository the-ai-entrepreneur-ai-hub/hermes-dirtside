"""Integration through the real core wrapper and a signed device."""
import os
import re
import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fake_device import FakeDevice
from gateway.session_context import clear_session_vars, set_session_vars
from nacl.signing import SigningKey
from network_support import until
from tools.file_operations import ShellFileOperations
from tools.interrupt import set_interrupt

from dirtside.environment import DirtsideEnvironment
from dirtside.model import MAX_OUTPUT_BYTES, Policy
from dirtside.provider import DirtsideProvider
from dirtside.protocol import ProtocolError, sign
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_executor import alive, await_file
from test_registry import paired


def device_setup(root, policy=None):
    registry = Registry(root / "data.db")
    device, token, key = paired(registry, root)
    relay = Relay(registry)
    return relay, device, FakeDevice(relay, device, token, key, policy)


def test_roundtrip_fake_device(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    relay.registry.set_target("chat", device.id)
    tokens = set_session_vars(session_key="chat")
    try:
        with fake:
            env = DirtsideProvider(relay.registry, relay).create_environment(cwd="~", timeout=120)
            assert isinstance(env._current(), DirtsideEnvironment)
            assert env._stdin_mode == "payload" and env._persistent
            assert not env._passwordless_sudo_probe_supported
            result = env.execute("pwd")
            assert result["returncode"] == 0 and result["output"].strip() == str(tmp_path)
            ops = ShellFileOperations(env)
            payload = "hello '地'\n" * 100000 + "tail"
            written = ops.write_file(str(tmp_path / "large.txt"), payload)
            assert not written.error and written.verified
            read = ops.read_file_raw(str(tmp_path / "large.txt"))
            assert not read.error and read.content == payload
            assert (tmp_path / "large.txt").read_bytes() == payload.encode()
            env.cleanup()
    finally:
        clear_session_vars(tokens)


def test_result_inline_tail(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        fake.posts.clear()
        assert env.execute("echo hi")["output"] == "hi\n"
        assert [kind for kind, _ in fake.posts] == ["result"]


def test_multibyte_chunks(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        command = f"{shlex.quote(sys.executable)} -c 'print(\"地\" * 70000, end=\"\")'"
        result = env.execute(command)
        assert result["returncode"] == 0 and result["output"] == "地" * 70000
        assert sum(kind == "chunk" for kind, _ in fake.posts) >= 3


def test_grandchild_returns(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        start = time.monotonic()
        result = env.execute("sleep 30 & echo $!")
        pid = int(result["output"])
        try:
            assert result["returncode"] == 0 and time.monotonic() - start < 1
        finally:
            if alive(pid):
                os.kill(pid, 15)


def test_grandchild_survives(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        result = env.execute("sleep 30 & echo $!")
        pid = int(result["output"])
        try:
            assert result["returncode"] == 0 and alive(pid)
        finally:
            if alive(pid):
                os.kill(pid, 15)


def test_timeout_retains_partial_and_kills_device_process(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        result = env.execute("echo $$ > pid; printf partial; sleep 60", timeout=1)
        assert result["returncode"] == 124 and result["output"] == "partial\n[Command timed out after 1s]"
        assert result["hermes_timed_out"] is True
        pid = int((tmp_path / "pid").read_text())
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            threading.Event().wait(0.05)
        assert not alive(pid)


def test_stop_retains_partial_and_kills_device_process(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        tids = []

        def execute():
            tids.append(threading.get_ident())
            try:
                return env.execute("echo $$ > pid; printf partial; sleep 60")
            finally:
                set_interrupt(False)

        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(execute)
            pid = int(await_file(tmp_path / "pid"))
            until(lambda: any(relay.tail(rid) == b"partial" for rid in list(relay.handles)))
            set_interrupt(True, tids[0])
            result = future.result(timeout=1)
        assert result["returncode"] == 130 and result["output"] == "partial\n[Command interrupted]"
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            threading.Event().wait(0.05)
        assert not alive(pid)


def test_device_cap_notice(tmp_path):
    relay, device, fake = device_setup(tmp_path, Policy((), 900, 1000, 4))
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        result = env.execute(f"{shlex.quote(sys.executable)} -c 'print(\"x\" * 200000)'")
        assert result["returncode"] == 0 and result["output"].startswith("x" * 1000)
        assert result["output"].endswith("[Dirtside: output capped at 1000 bytes on the device]")


def test_unwrapped_command_policy_and_preview(tmp_path):
    relay, device, fake = device_setup(tmp_path, Policy((re.compile("forbidden"),), 900, MAX_OUTPUT_BYTES, 4))
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        result = env.execute("touch forbidden")
        assert result["returncode"] == 126 and not (tmp_path / "forbidden").exists()
        assert "command matches deny pattern" in result["output"]
        assert relay.registry.recent(1)[0].preview == "touch forbidden"
        assert env.execute("echo safe")["output"] == "safe\n"


def test_concurrent_commands_keep_their_policy_identity(tmp_path):
    relay, device, fake = device_setup(tmp_path, Policy((re.compile("forbidden"),), 900, MAX_OUTPUT_BYTES, 4))
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        commands = [f"touch forbidden-{n}" if n % 2 else f"printf allowed-{n}" for n in range(12)]
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(env.execute, commands))
        for command, result in zip(commands, results):
            assert result["returncode"] == (126 if "forbidden" in command else 0)
        assert not list(tmp_path.glob("forbidden-*"))
        rows = relay.registry.recent(12)
        assert {row.preview for row in rows} == set(commands)
        assert all(row.exit_code == (126 if "forbidden" in row.preview else 0) for row in rows)


def test_unverified_contact_does_not_mark_online(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    try:
        wire = sign(SigningKey.generate(), "poll", device.id, {})
        with pytest.raises(ProtocolError):
            fake._accept(wire)
        assert not relay.is_online(device.id)
        fake.token = "not-a-bearer"
        with pytest.raises(PermissionError):
            fake._accept(sign(fake.key, "poll", device.id, {}))
        assert not relay.is_online(device.id)
    finally:
        fake.pool.shutdown(wait=True)
