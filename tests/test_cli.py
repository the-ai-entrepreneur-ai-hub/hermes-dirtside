"""CLI parser attachment and private local status through the real core."""
import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from hermes_cli.main import _attach_plugin_cli_command
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from network_support import DESKTOP_TOKEN, generic_poll_rejections, listening, mounted, subprocess_agent, until
from tools.interrupt import set_interrupt

from dirtside.agent.activity import Activity
from dirtside.agent.config import DeviceConfig
from dirtside.cli import handle, setup_parser
from dirtside.environment import DirtsideEnvironment
from test_agent import config
from test_executor import alive, await_file


def parser():
    root = argparse.ArgumentParser()
    _attach_plugin_cli_command(root.add_subparsers(), dict(name="dirtside", help="Personal device",
                                                         setup_fn=setup_parser, handler_fn=handle))
    return root


def test_cli_parser_and_status(tmp_path, capsys):
    scope = set_hermes_home_override(tmp_path)
    try:
        cfg = config()
        cfg.save()
        activity = Activity()
        activity.write("contact")
        activity.write("finished", id="r_" + "12" * 12, exit_code=0)
        activity.close()
        args = parser().parse_args(["dirtside", "status"])
        assert args.func(args) is None
        output = capsys.readouterr().out
        assert "paired to http://127.0.0.1:1, online" in output
        assert "parallel 4" in output and "exit=0" in output
        assert cfg.token not in output and bytes(cfg.key).hex() not in output
        assert parser().parse_args(["dirtside", "serve"]).dirtside_action == "serve"
        assert (tmp_path / "dirtside" / "agent.log").stat().st_mode & 0o777 == 0o600
    finally:
        reset_hermes_home_override(scope)


def test_cli_unpaired_is_actionable(tmp_path, capsys):
    scope = set_hermes_home_override(tmp_path)
    try:
        args = parser().parse_args(["dirtside", "status"])
        assert args.func(args) == 1
        assert "Pair this device first" in capsys.readouterr().out
    finally:
        reset_hermes_home_override(scope)


def test_cli_pair_real_http_pwd_cd_stop_revoke(tmp_path, capsys):
    install = tmp_path / "device-install"
    retried = threading.Event()
    with mounted(tmp_path) as (app, reg, relay, _), listening(generic_poll_rejections(app, retried)) as url:
        code = reg.mint("laptop", int(time.time()))
        scope = set_hermes_home_override(install)
        try:
            args = parser().parse_args(["dirtside", "pair", url, "--name", "laptop", "--code=" + code])
            assert args.func(args) is None
            cfg = DeviceConfig.load()
            output = capsys.readouterr().out
            assert "Paired laptop" in output and cfg.token not in output and code not in output
            assert (install / "dirtside" / "device.json").stat().st_mode & 0o777 == 0o600
        finally:
            reset_hermes_home_override(scope)
        device = reg.active_device("laptop")
        with subprocess_agent(cfg, install) as proc:
            until(lambda: relay.is_online(device.id))
            remote = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
            assert remote.execute("pwd")["output"] == device.home + "\n"
            assert remote.execute(f"cd '{tmp_path}'")["returncode"] == 0
            assert remote.execute("pwd")["output"] == str(tmp_path) + "\n"
            assert remote.cwd == str(tmp_path)
            ids = []
            def execute():
                ids.append(threading.get_ident())
                try:
                    return remote.execute("echo $$ > stop.pid; printf partial; sleep 60")
                finally:
                    set_interrupt(False)
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(execute)
                pid = int(await_file(tmp_path / "stop.pid"))
                until(lambda: any(b"partial" in relay.tail(rid) for rid in relay.handles))
                start = time.monotonic()
                set_interrupt(True, ids[0])
                result = future.result(timeout=1)
                assert result["returncode"] == 130 and "partial" in result["output"]
                until(lambda: not alive(pid), timeout=5)
                assert time.monotonic() - start < 5
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(remote.execute, "echo $$ > revoke.pid; sleep 60")
                pid = int(await_file(tmp_path / "revoke.pid"))
                with httpx.Client(headers={"Authorization": f"Bearer {DESKTOP_TOKEN}"}) as client:
                    assert client.post(url + "/api/plugins/dirtside/devices/laptop/revoke").status_code == 200
                assert future.result(timeout=1)["returncode"] == 130
                assert retried.wait(5) and proc.poll() is None
                proc.terminate()
                assert proc.wait(timeout=5) == 0
                assert not alive(pid) and not relay.is_online(device.id)
            remote.cleanup()


def test_cli_pair_failure_is_private(tmp_path, capsys):
    scope = set_hermes_home_override(tmp_path)
    try:
        args = parser().parse_args(["dirtside", "pair", "http://remote.invalid", "--name", "device",
                                    "--code", "private-code"])
        assert args.func(args) == 1
        output = capsys.readouterr().out
        assert "Pairing failed" in output and "private-code" not in output
        assert not (tmp_path / "dirtside" / "device.json").exists()
    finally:
        reset_hermes_home_override(scope)
