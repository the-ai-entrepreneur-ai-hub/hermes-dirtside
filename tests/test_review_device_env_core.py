"""Credential isolation through the real Hermes serve CLI and terminal."""
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from core_rig import Core, Rig, until

from test_review_device_env import SECRET_NAMES


class CliRig(Rig):
    def start_agent(self):
        self.agent_log = (self.device_home / "agent-process.log").open("a")
        started = time.time()
        command = [str(Path(sys.executable).with_name("hermes")), "dirtside", "serve"]
        self.agent = subprocess.Popen(command, cwd=self.device_home, env=self.device_env,
                                      stdin=subprocess.DEVNULL, stdout=self.agent_log,
                                      stderr=subprocess.STDOUT, start_new_session=True)
        until(lambda: self.online(since=started), timeout=20)
        return self


@pytest.mark.parametrize("transport", ["in-process", "client"])
def test_serve_dotenv_isolation(tmp_path, transport):
    with CliRig(tmp_path / "rig") as rig, ExitStack() as stack:
        rig.pair()
        secrets = {name: "fake-dotenv-" + name.lower() for name in SECRET_NAMES}
        (rig.device_home / ".env").write_text("".join(f"{k}={v}\n" for k, v in secrets.items()))
        rig.start_agent()
        core = stack.enter_context(Core(rig.core.home, env=rig.core.env, worker=True)) if transport == "client" else rig.core
        core.call("slash", session="chat", raw_args="use " + rig.name)
        result = core.terminal("env")
        assert result["exit_code"] == 0, result
        output = result["output"]
        assert all(name not in output and value not in output for name, value in secrets.items())
        basics = core.terminal("command -v sh; pwd; printf '%s' \"$HOME\"")
        assert basics["exit_code"] == 0
        assert basics["output"].splitlines()[-2:] == [rig.device_env["HOME"]] * 2
    assert rig.agent.returncode == 0 and core.proc.returncode == 0
