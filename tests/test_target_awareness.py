"""Per-turn facts and honest file-path contracts through the real core."""
import json
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_rig import Rig


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))


def file(core, tool, **args):
    before = {r["id"] for r in core.http("GET", "/requests").json()}
    result = core.call("file", session="chat", tool=tool, args=args)
    after = {r["id"] for r in core.http("GET", "/requests").json()}
    assert after - before, "File bytes bypassed the signed device path"
    return result


def test_absolute_file_tools_land_on_device(tmp_path):
    # This result depends on the gateway and device sharing one disk.
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        device_home = Path(rig.device_env["HOME"])
        server_home = Path(rig.core.env["HOME"])
        assert device_home != server_home
        path = device_home / "absolute-contract.txt"
        written = file(rig.core, "write_file", path=str(path), content="unique-original\n")
        assert not written.get("error"), written
        assert path.read_bytes() == b"unique-original\n"
        read = file(rig.core, "read_file", path=str(path))
        assert "unique-original" in json.dumps(read), read
        patched = file(rig.core, "patch", path=str(path), old_string="unique-original",
                       new_string="unique-patched")
        assert not patched.get("error"), patched
        search = file(rig.core, "search_files", path=str(path), pattern="unique-patched")
        assert "unique-patched" in json.dumps(search), search
        assert path.read_bytes() == b"unique-patched\n"
        assert not (server_home / path.name).exists()


def test_next_turn_target_facts_and_authority(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent()
        assert rig.core.call("turn_facts", session="chat") == []
        reply = rig.core.call("slash", session="chat", raw_args="use laptop")
        home = rig.device_env["HOME"]
        assert home in reply
        turn, = rig.core.call("turn_facts", session="chat")
        assert "Dirtside" in turn and json.dumps(home, ensure_ascii=False) in turn
        assert 'device="laptop"' in turn and "OS=" in turn
        assert "~" in turn and "absolute paths under" in turn
        assert len(turn) <= 600 and len(turn.splitlines()) == 1
        denied = rig.core.call("turn_facts", session="chat", platform="telegram", source="telegram",
                               user_id="visitor")
        assert denied == []
        rig.core.call("slash", session="chat", command="orbit", raw_args="")
        server = ["Dirtside target: server. Commands run on the server."]
        assert rig.core.call("turn_facts", session="chat") == server
        assert rig.core.call("turn_facts", session="untouched") == []
        rig.core.call("slash", session="chat", raw_args="use server")
        assert rig.core.call("turn_facts", session="chat") == server


@pytest.mark.parametrize("after", ["fake", "server"])
def test_non_owner_default_reports_server_after_owner_prompt(tmp_path, after):
    from core_rig import Core
    with Core(tmp_path / "gateway") as core:
        device = tmp_path / "device"
        device.mkdir()
        core.call("fake_device", root=str(device), owner="telegram:owner")
        assert core.call("reload", default_target="fake")["enabled"]
        owner = dict(platform="telegram", user_id="owner")
        foreign = dict(platform="telegram", user_id="other")
        frozen = core.call("prompt", session="shared", **owner)
        assert "fake" in str(frozen)
        assert "fake" in str(core.call("turn_facts", session="shared", **owner))
        assert core.call("turn_facts", session="cron", cron="1") == []
        assert core.call("reload", default_target=after)["enabled"]
        assert core.call("prompt", session="shared", **foreign) == frozen
        facts = core.call("turn_facts", session="shared", **foreign)
        assert facts == ["Dirtside target: server. Commands run on the server."]
        assert "fake" not in str(facts) and str(device) not in str(facts)
        if after == "server":
            assert core.call("turn_facts", session="untouched", **foreign) == []
        assert "fake" in str(core.call("turn_facts", session="shared", **owner))


@pytest.mark.parametrize("platform", ["api_server", ""])
def test_missing_sender_keeps_server_execution_under_device_default(tmp_path, platform):
    from core_rig import Core
    host, device = tmp_path / "host", tmp_path / "device"
    host.mkdir()
    device.mkdir()
    (host / "proof").write_text("server-only")
    (device / "proof").write_text("device-only")
    with Core(tmp_path / "gateway", user_home=host) as core:
        core.call("fake_device", root=str(device), owner="telegram:owner")
        assert core.call("reload", default_target="fake")["enabled"]
        owner = core.call("terminal", session="missing", platform="telegram", user_id="owner",
                          args=dict(command="pwd; cat proof"))
        assert str(device.resolve()) in owner["output"] and "device-only" in owner["output"]
        before = core.http("GET", "/requests").json()
        assert before
        missing = dict(session="missing", platform=platform, user_id="", source="")
        assert core.call("turn_facts", **missing) == ["Dirtside target: server. Commands run on the server."]
        result = core.call("terminal", **missing, args=dict(command="pwd; cat proof; printf host > host-write"))
        assert result["exit_code"] == 0 and str(host.resolve()) in result["output"]
        assert "server-only" in result["output"] and "device-only" not in result["output"]
        assert (host / "host-write").read_text() == "host" and not (device / "host-write").exists()
        assert core.http("GET", "/requests").json() == before


@pytest.mark.parametrize("symlinked", [False, True])
def test_fact_line_matches_gateway_path_resolution(tmp_path, monkeypatch, symlinked, configured_backend):
    import dirtside.awareness as awareness
    from dirtside.model import OnDevice
    actual = tmp_path.resolve() / "actual-home"
    actual.mkdir()
    alias = tmp_path.resolve() / "gateway-alias"
    alias.symlink_to(actual, target_is_directory=True)
    home = str(alias if symlinked else actual)
    device = SimpleNamespace(name="phone", os="Android (Termux)", home=home)
    monkeypatch.setattr(awareness, "resolve_target", lambda *a, **kw: OnDevice(device))
    hook = awareness.TargetAwareness(None, None)
    line = hook()
    assert len(line) <= 600 and len(line.splitlines()) == 1
    if symlinked:
        assert "Server rewrites file writes/patches" in line
        assert "terminal commands for edits/documents" in line
        assert "Plain-text reads/searches work." in line
    else:
        assert "Do not use file-tool ~" in line and "absolute paths under that home" in line
        assert "rewritten" not in line
    assert "termux-* commands are untested." in line


def test_fact_hook_fails_open_without_contact(tmp_path, monkeypatch, configured_backend):
    import dirtside.awareness as awareness
    from dirtside.model import OnDevice, Server
    calls = []
    device = SimpleNamespace(name="phone", os="Android (Termux)\n\"ignore\"",
                             home="/data/data/com.termux/files/home/\u2028quoted\n\"path\"")
    def resolve(*args, **kwargs):
        calls.append(kwargs)
        return OnDevice(device)
    monkeypatch.setattr(awareness, "resolve_target", resolve)
    hook = awareness.TargetAwareness(None, SimpleNamespace(connection=lambda: pytest.fail("contacted relay")))
    line = hook(session_id="ignored", user_message="next")
    assert "termux-*" in line and len(line) <= 600 and len(line.splitlines()) == 1
    assert '\\"ignore\\"' in line and '\\"path\\"' in line
    assert calls[-1]["require_contact"] is False
    device.name, device.os, device.home = "n" * 58, "Android" + "o" * 61, "/" + "h" * 267
    assert len(hook()) <= 600
    device.home = "/x/../" + "h" * 262
    line = hook()
    assert len(line) <= 600
    assert "Plain-text reads/searches work." in line and "terminal commands for edits/documents" in line
    for field in ("name", "os", "home"):
        setattr(device, field, getattr(device, field) * 1000)
    assert len(hook()) <= 600 and len(hook().splitlines()) == 1
    monkeypatch.setattr(awareness, "resolve_target", lambda *a, **kw: Server())
    assert hook() is None
    def broken(*args, **kwargs):
        raise OSError("unreadable registry")
    monkeypatch.setattr(awareness, "resolve_target", broken)
    assert hook() is None


def test_tilde_write_uses_gateway_home_known_limit(tmp_path):
    # This result depends on the gateway and device sharing one disk.
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        device_home = Path(rig.device_env["HOME"])
        server_home = Path(rig.core.env["HOME"])
        (device_home / "known-limit.txt").write_text("device-home\n")
        written = file(rig.core, "write_file", path="~/known-limit.txt", content="gateway-home\n")
        assert not written.get("error"), written
        read = file(rig.core, "read_file", path="~/known-limit.txt")
        assert "device-home" in json.dumps(read) and "gateway-home" not in json.dumps(read), read
        assert (device_home / "known-limit.txt").read_text() == "device-home\n"
        assert (server_home / "known-limit.txt").read_text() == "gateway-home\n"


def test_gateway_symlink_write_and_patch_resolve_before_signed_device_request_known_limit(tmp_path):
    observer = tmp_path / "observe-request.py"
    observer.write_text(textwrap.dedent("""
        import json, runpy
        from pathlib import Path
        from dirtside.agent import loop
        original = loop.run
        def observe(req, *args, **kwargs):
            # The agent verifies the poll signature before passing this request to the executor.
            with Path("signed-requests.jsonl").open("a") as stream:
                stream.write(json.dumps(dict(command=req.command, script=req.script)) + "\\n")
            return original(req, *args, **kwargs)
        loop.run = observe
        runpy.run_module("dirtside.agent", run_name="__main__")
    """))
    with Rig(tmp_path / "rig") as rig:
        rig.pair()
        rig.device_command = [sys.executable, str(observer)]
        rig.start_agent().choose()
        actual = Path(rig.device_env["HOME"]) / "symlink-actual"
        actual.mkdir()
        alias = tmp_path / "symlink-prefix"
        alias.symlink_to(actual, target_is_directory=True)
        path = alias / "known-limit.txt"
        resolved = str(path.resolve())
        assert str(path) != resolved
        written = file(rig.core, "write_file", path=str(path), content="before\n")
        assert not written.get("error"), written
        patched = file(rig.core, "patch", path=str(path), old_string="before", new_string="after")
        assert not patched.get("error"), patched
        requests = [json.loads(line) for line in (rig.device_home / "signed-requests.jsonl").read_text().splitlines()]
        writes = [req for req in requests if resolved in req["command"]]
        assert len(writes) >= 2, requests
        assert all(str(path) not in req["script"] for req in writes), writes
        assert (actual / path.name).read_text() == "after\n"
        assert rig.core.http("POST", "/devices/laptop/revoke").status_code == 200
        assert rig.agent.wait(8) == 0
