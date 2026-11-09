"""Current senders share a real core cache, never each other's device authority."""
import json
import re
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest
from core_rig import Core, Rig


def as_user(core, method, user, **args):
    return core.call(method, session=args.pop("session", "shared-group"),
                     source="telegram", platform="telegram", user_id=user, **args)


def owned_pair(rig, user="A", session="shared-group"):
    reply = as_user(rig.core, "slash", user, session=session, raw_args="pair " + rig.name)
    code = re.search(r"--code=(\S+)", reply)[1]
    result = subprocess.run([str(Path(sys.executable).with_name("hermes")), "dirtside", "pair",
                             rig.core.url, "--name", rig.name, "--code=" + code],
                            cwd=rig.device_home, env=rig.device_env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    rig.config = json.loads((rig.device_home / "dirtside" / "device.json").read_text())
    rig.start_agent()
    return rig


@pytest.mark.parametrize("transport", ["in-process", "client"])
@pytest.mark.parametrize("tool", ["terminal", "file"])
def test_group_dispatch(tmp_path, transport, tool):
    with Rig(tmp_path / "rig") as rig, ExitStack() as stack:
        owned_pair(rig)
        core = stack.enter_context(Core(rig.core.home, env=rig.core.env, worker=True)) if transport == "client" else rig.core
        as_user(core, "slash", "A", raw_args="use " + rig.name)
        good = as_user(core, "terminal", "A", task_id="shared-cache", args={"command": "printf owner"})
        assert good["exit_code"] == 0 and good["output"] == "owner"
        before = rig.core.http("GET", "/requests").json()
        marker = tmp_path / "borrowed"
        if tool == "terminal":
            result = as_user(core, tool, "B", task_id="shared-cache",
                             args={"command": f"printf borrowed > '{marker}'"})
        else:
            result = as_user(core, tool, "B", tool="write_file", task_id="shared-cache",
                             args={"path": str(marker), "content": "borrowed"})
        assert result.get("error") or result.get("exit_code", 0) != 0, result
        assert not marker.exists()
        assert rig.core.http("GET", "/requests").json() == before
        assert "laptop" not in as_user(core, "slash", "B", raw_args="devices")
        as_user(core, "slash", "B", raw_args="use server")
        assert as_user(core, "terminal", "B", args={"command": "pwd"})["output"].strip() == rig.core.env["HOME"]


@pytest.mark.parametrize("transport", ["in-process", "client"])
def test_owned_default(tmp_path, transport):
    with Rig(tmp_path / "rig") as rig, ExitStack() as stack:
        owned_pair(rig)
        old = rig.core
        rig.stop_agent()
        old.close()
        path = old.home / "config.yaml"
        config = json.loads(path.read_text())
        config["plugins"]["entries"]["dirtside"]["settings"]["default_target"] = rig.name
        path.write_text(json.dumps(config))
        rig.core = Core(old.home, env=old.env, port=old.info["port"])
        rig.start_agent()
        core = stack.enter_context(Core(rig.core.home, env=rig.core.env, worker=True)) if transport == "client" else rig.core
        as_user(core, "slash", "A", raw_args="devices")
        prompt = as_user(core, "prompt", "B", snapshot="B-default")
        assert "server" in str(prompt).lower() and "laptop" not in str(prompt)
        result = as_user(core, "terminal", "B", args={"command": "pwd"})
        assert result["exit_code"] == 0 and result["output"].strip() == rig.core.env["HOME"]
        cron = as_user(core, "terminal", "A", cron="1", args={"command": "pwd"})
        assert cron["exit_code"] == 0 and cron["output"].strip() == rig.core.env["HOME"]
        as_user(core, "slash", "A", raw_args="use " + rig.name)
        selected = core.call("terminal", session="shared-group", platform="", source="", user_id="", cron="1",
                             args={"command": "pwd"})
        assert selected["exit_code"] == 0 and selected["output"].strip() == rig.device_env["HOME"]


def test_owner_rechecks_worker_config(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        owned_pair(rig)
        path = rig.core.home / "config.yaml"
        config = json.loads(path.read_text())
        config["plugins"]["entries"]["dirtside"]["settings"]["owners"] = ["telegram:B"]
        path.write_text(json.dumps(config))
        with Core(rig.core.home, env=rig.core.env, worker=True) as worker:
            as_user(worker, "slash", "B", raw_args="use " + rig.name)
            marker = tmp_path / "worker-config-cannot-grant-owner-authority"
            result = as_user(worker, "terminal", "B", args={"command": f"touch '{marker}'"})
            assert result["exit_code"] != 0 and not marker.exists(), result
