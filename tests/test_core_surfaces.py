"""Conversation controls must reach cached core terminal and file entry points."""
import shlex
from pathlib import Path

from core_rig import Rig
from test_review_device_owners_core import as_user, owned_pair


def test_target_put_redirects_cached_terminal_and_file_operations(tmp_path):
    workdir = tmp_path / "cwd with spaces"
    workdir.mkdir()
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent()
        core = rig.core
        server_home, device_home = core.env["HOME"], rig.device_env["HOME"]
        assert core.terminal("pwd")["output"].strip() == server_home
        cached = core.call("state", session="chat")["identity"]
        path = "/sessions/chat/target"
        assert core.http("PUT", path, json={"target": rig.name}).status_code == 200
        assert core.terminal("printf '%s' \"$HOME\"")["output"] == device_home
        written = core.call("file", session="chat", tool="write_file",
                            args=dict(path=str(Path(device_home) / "target.txt"), content="device"))
        assert not written.get("error"), written
        assert (Path(device_home) / "target.txt").read_text() == "device"
        assert not (Path(server_home) / "target.txt").exists()
        assert core.terminal("export TARGET_SIDE=device; cd " + shlex.quote(str(workdir)))["exit_code"] == 0
        assert core.http("PUT", path, json={"target": "server"}).status_code == 200
        assert core.terminal("printf '%s' \"$HOME\"")["output"] == server_home
        assert core.terminal("echo ${TARGET_SIDE-unset}")["output"].strip() == "unset"
        assert core.http("PUT", path, json={"target": rig.name}).status_code == 200
        assert core.terminal("pwd")["output"].strip() == str(workdir.resolve())
        assert core.terminal("echo $TARGET_SIDE")["output"].strip() == "device"
        assert core.call("state", session="chat")["identity"] == cached
        rows = core.http("GET", "/requests?session_key=chat").json()
        assert rows and all(row["device_id"] == rig.config["device_id"] for row in rows)
        assert core.http("POST", f"/devices/{rig.name}/revoke").status_code == 200
        marker = tmp_path / "must-not-run"
        refused = core.terminal("printf forbidden > " + shlex.quote(str(marker)), timeout=10)
        assert "no longer paired" in str(refused) and refused["exit_code"] != 0
        assert not marker.exists()
        assert core.http("PUT", path, json={"target": "server"}).status_code == 200
        assert core.terminal("printf '%s' \"$HOME\"")["output"] == server_home


def test_registered_command_changes_telegram_context_and_core_freezes_prompt(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        owned_pair(rig, user="42", session="telegram:42")
        core, session = rig.core, "telegram:42"
        def call(method, **params):
            return as_user(core, method, "42", session=session, **params)
        assert call("terminal", args=dict(command="printf '%s' \"$HOME\""))["output"] == core.env["HOME"]
        reply = call("slash", raw_args="use " + rig.name)
        assert "from the next command" in reply
        assert call("terminal", args=dict(command="printf '%s' \"$HOME\""))["output"] == rig.device_env["HOME"]
        section = call("prompt")
        assert len(section) == 1 and rig.name in section[0] and len(section[0]) <= 600
        assert call("slash", raw_args="use server")
        assert call("prompt") == section
        assert call("prompt", snapshot="new-agent") == []
        assert call("terminal", args=dict(command="printf '%s' \"$HOME\""))["output"] == core.env["HOME"]
        assert "Revoked" in call("slash", raw_args="revoke " + rig.name)
        assert core.http("GET", "/devices").json() == []
