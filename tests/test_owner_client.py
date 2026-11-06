"""Core terminal in this test process reaches a separately mounted fake-device owner."""
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
from agent.terminal_env_registry import register_provider, restore_registration, snapshot_registration
from core_rig import Core, until
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_cli.plugin_command_dispatch import invoke_plugin_command
from tools.interrupt import set_interrupt
from tools.terminal_tool import terminal_tool
from tools.terminal_tool_lifecycle import cleanup_all_environments
from dirtside.client import Client
from dirtside.commands import Commands
from dirtside.environment import DirtsideEnvironment, EnvironmentConnectionError
from dirtside.prompt import TargetPrompt
from dirtside.provider import DirtsideProvider
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_executor import alive
from test_network import stop_group
from test_core_terminal import semantic

@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    with Core(tmp_path / "owner", user_home=work) as owner:
        owner.call("fake_device", root=str(work))
        assert owner.http("GET", "/devices").json()[0]["online"]
        registry = Registry(Path(owner.info["registry"]))
        device = registry.active_device("fake")
        relay = Relay(registry)
        relay._client = client = Client(relay)
        provider = DirtsideProvider(registry, relay)
        previous = snapshot_registration("dirtside")
        register_provider(provider)
        monkeypatch.setenv("TERMINAL_ENV", "dirtside")
        monkeypatch.setenv("TERMINAL_CWD", str(work))
        registry.set_target("client-test", device.id)
        owner.call("target", session="owner-test", name="fake")
        try:
            yield owner, registry, relay, device, work
        finally:
            cleanup_all_environments()
            restore_registration("dirtside", provider, previous)
            client.http.close()

def terminal(command, **options):
    tokens = set_session_vars(session_key="client-test", session_id="client-test", source="cli")
    try:
        return json.loads(terminal_tool(command=command, task_id="client-test", **options))
    finally:
        set_interrupt(False)
        clear_session_vars(tokens)

def normalized(result):
    if path := result.get("full_output_path"):
        return semantic(result | {"output": result["output"].replace(path, "<recovery>")})
    return semantic(result)

def test_core_terminal_cross_process_matches_owner_and_logs(owner_client):
    owner, registry, relay, _, work = owner_client
    commands = ["pwd", "head -c 1048576 /dev/zero | tr '\\0' x", "printf partial; sleep 5"]
    for command in commands:
        options = {"timeout": 1} if command.endswith("sleep 5") else {}
        actual = terminal(command, **options)
        expected = owner.terminal(command, session="owner-test", **options)
        assert normalized(actual) == normalized(expected)
        if "full_output_path" in actual:
            recovered = [Path(r["full_output_path"]).read_bytes() for r in (actual, expected)]
            recovered = [re.sub(br"(__HERMES_(?:PIPE|CWD)_)[a-f0-9]{12}__", br"\1session__", d)
                         for d in recovered]
            assert recovered[0] == recovered[1] and recovered[0].startswith(b"x" * 1048576)
        if options:
            assert actual["exit_code"] == 124 and actual["output"] == "partial\n[Command timed out after 1s]"
    rows = owner.http("GET", "/requests").json()
    for key in ("client-test", "owner-test"):
        assert set(commands) <= {r["preview"] for r in rows if r["session_key"] == key}
    timed = [r for r in registry.recent(50) if r.preview == commands[-1]]
    assert len(timed) == 2 and {(r.state.value, r.exit_code) for r in timed} == {("cancelled", 130)}
    assert not relay.handles and not relay.last_seen and relay._owner_pid is None
    assert terminal("pwd")["output"] == str(work.resolve())

def test_core_kill_and_slash_worker_keep_owner_state(owner_client):
    owner, _, relay, device, work = owner_client
    command = "printf retained; echo $$ > stop.pid; while :; do sleep 1; done"
    expected = owner.submit("terminal", session="owner-test", args={"command": command})
    def running(key):
        return next((r for r in owner.http("GET", "/requests").json()
                     if r["session_key"] == key and r["preview"] == command and r["tail"] == "retained"), None)
    until(lambda: running("owner-test"))
    owner.call("interrupt", call_id=expected.call_id)
    expected = expected.result(3)
    tids = []
    def execute():
        tids.append(threading.get_ident())
        return terminal(command)
    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(execute)
        try:
            row = until(lambda: running("client-test"))
            pid = int((work / "stop.pid").read_text())
            with Core(owner.home, env=owner.env, worker=True) as slash:
                assert slash.proc.pid not in (os.getpid(), owner.proc.pid)
                assert running("client-test")["state"] == "running"
                for raw in ("devices", "", "use fake"):
                    text = slash.call("slash", session="client-test", raw_args=raw)
                    assert "online" in text and "offline" not in text
                assert "online" in slash.call("prompt", session="client-test")[0]
            assert running("client-test")["state"] == "running"
            set_interrupt(True, tids[0])
            actual = result.result(3)
        finally:
            if not result.done():
                owner.call("cancel", request_id=row["id"])
                result.result(3)
    assert semantic(actual) == semantic(expected)
    assert actual["exit_code"] == 130 and actual["output"] == "retained\n[Command interrupted]"
    until(lambda: not alive(pid), timeout=5)
    ended = next(r for r in owner.http("GET", "/requests").json() if r["id"] == row["id"])
    assert ended["state"] == "cancelled" and ended["exit_code"] == 130
    assert relay.connection().is_online(device.id)

def test_worker_commands_prompt_and_revoke_use_owner(owner_client):
    owner, registry, relay, device, work = owner_client
    tokens = set_session_vars(session_key="client-test")
    commands = Commands(SimpleNamespace(ask_choice=lambda *_: "fake"), registry, relay)
    try:
        for args in ("", "devices", "use fake", "use"):
            assert "online" in invoke_plugin_command(commands, args)
        assert "online" in TargetPrompt(registry, relay).current_target_section({})
        env = DirtsideEnvironment(relay, device, "client-test", "revoke", str(work), 120)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(env.execute, "printf revoking; while :; do sleep 1; done")
            until(lambda: any(r["tail"] == "revoking" for r in owner.http("GET", "/requests").json()))
            assert commands("revoke fake") == "Revoked fake and cancelled its live requests."
            assert future.result(3)["returncode"] == 130
    finally:
        clear_session_vars(tokens)

def test_owner_death_never_falls_back(owner_client):
    owner, _, relay, device, work = owner_client
    env = DirtsideEnvironment(relay, device, "client-test", "dead", str(work), 120)
    owner.proc.kill()
    owner.proc.wait(3)
    marker = work / "must-not-run"
    with pytest.raises(EnvironmentConnectionError, match="device 'fake' is offline"):
        env.execute(f"touch '{marker}'")
    assert not marker.exists() and not relay.handles

def test_core_owner_loss_midstream_has_no_timeout_hint(owner_client, monkeypatch):
    from dirtside.client import OWNER_MISSING
    owner, _, relay, _, work = owner_client
    assert terminal("true")["exit_code"] == 0
    delivered, write = threading.Event(), relay._write
    def observe(handle, fd, data, deadline):
        accepted = write(handle, fd, data, deadline)
        if accepted and data == b"retained":
            delivered.set()
        return accepted
    monkeypatch.setattr(relay, "_write", observe)
    command = "echo $$ > owner-loss.pid; printf retained; while :; do sleep 1; done"
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(terminal, command)
        try:
            assert delivered.wait(8)
            owner.proc.kill()
            owner.proc.wait(3)
            result = future.result(5)
            assert result["exit_code"] == 255
            assert result["output"] == f"retained\n[Dirtside: {OWNER_MISSING}]"
            assert not result.get("hermes_timed_out") and not result.get("hint")
            assert "Exit 124:" not in str(result)
        finally:
            if owner.proc.poll() is None:
                owner.proc.kill()
                owner.proc.wait(3)
            if (work / "owner-loss.pid").exists():
                stop_group(int((work / "owner-loss.pid").read_text()))
