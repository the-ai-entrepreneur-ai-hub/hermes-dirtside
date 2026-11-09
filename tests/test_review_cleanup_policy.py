"""Cleanup authority and device policy survive lifecycle operations."""
import json
import threading
import time
from contextvars import Context
from dataclasses import replace
from pathlib import Path

import pytest
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from network_support import listening, mounted

from dirtside.access import Access
from dirtside.agent.config import DeviceConfig, default_policy
from dirtside.cli import handle
from dirtside.environment import EnvironmentConnectionError, _COMMAND
from dirtside.provider import DirtsideProvider
from fake_device import FakeDevice
from test_cli import parser
from test_review_name_safety import actor, pair_as
from dirtside.registry import Registry
from dirtside.relay import Relay


@pytest.mark.parametrize("mode", ["idle", "shutdown"])
@pytest.mark.parametrize("owner", ["local", "telegram:alice"])
def test_context_free_cleanup_removes_only_its_snapshot(tmp_path, monkeypatch, mode, owner):
    import tools.terminal_tool as terminal
    from tools.terminal_tool_lifecycle import _cleanup_inactive_envs, cleanup_all_environments
    from hermes_cli.plugin_session import session_surface
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    device, token, key = pair_as(reg, relay, tmp_path, owner)
    with actor(owner) as ctx, FakeDevice(relay, device, token, key):
        ctx.session_cwd = lambda: str(tmp_path)
        ctx.session_surface = session_surface
        access = relay.access = Access(ctx)
        reg.set_target("shared-group", device.id)
        env = DirtsideProvider(reg, relay, access=access).create_environment(cwd="~", timeout=120)
        assert env.execute("printf ready")["output"] == "ready"
        snapshot = Path(env._last._snapshot_path)
        stale = Path(str(snapshot) + ".tmp.stale")
        stale.write_text("partial")
        unrelated = tmp_path / "keep.sh"
        unrelated.write_text("keep")
        assert snapshot.exists()
        monkeypatch.setattr(terminal, "_active_environments", {"cleanup-test": env})
        monkeypatch.setattr(terminal, "_last_activity", {"cleanup-test": 0})
        monkeypatch.setattr(terminal, "_calls_in_flight", {})
        errors, identities = [], []

        def reap():
            try:
                identities.append(access.identity())
                with pytest.raises(EnvironmentConnectionError):
                    env.execute("touch model-command-must-not-run")
                command = _COMMAND.set("touch model-command-must-not-run")
                try:
                    if mode == "idle":
                        _cleanup_inactive_envs(lifetime_seconds=0)
                    else:
                        cleanup_all_environments()
                finally:
                    _COMMAND.reset(command)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=lambda: Context().run(reap))
        thread.start()
        thread.join(15)
        assert not thread.is_alive() and not errors, errors
        assert identities == [""]
        assert not snapshot.exists() and not stale.exists()
        assert unrelated.read_text() == "keep" and not (tmp_path / "model-command-must-not-run").exists()
        assert reg.recent(1)[0].preview == ""
        assert reg.recent(1)[0].exit_code == 0


def test_repair_preserves_passthrough_names(tmp_path, monkeypatch, capsys):
    home = tmp_path / "device"
    home.mkdir()
    monkeypatch.setenv("OWNER_SOCKET", "fake-value-never-print")
    with mounted(tmp_path / "gateway") as (app, reg, *_), listening(app) as url:
        scope = set_hermes_home_override(home)
        try:
            def pair():
                code = reg.mint("laptop", int(time.time()))
                args = parser().parse_args(["dirtside", "pair", url, "--name", "laptop", "--code=" + code])
                assert handle(args) is None
                output = capsys.readouterr().out
                assert code not in output and "fake-value-never-print" not in output
                return DeviceConfig.load()
            fresh = pair()
            assert fresh.policy.env_passthrough == ()
            names = ("OWNER_SOCKET", "UNSET_NAME")
            replace(fresh, policy=replace(fresh.policy, env_passthrough=names, max_parallel=2)).save()
            repaired = pair()
            assert repaired.policy.env_passthrough == names
            assert repaired.policy.max_parallel == default_policy().max_parallel
            assert repaired.device_id == fresh.device_id and repaired.token != fresh.token
            data = json.loads((home / "dirtside/device.json").read_text())
            assert data["policy"]["env_passthrough"] == list(names)
            assert "fake-value-never-print" not in json.dumps(data)
        finally:
            reset_hermes_home_override(scope)


@pytest.mark.parametrize("damage", ["unreadable", "permissions", "malformed", "missing-fields"])
def test_repair_recovers_bad_existing_config_with_empty_names(tmp_path, monkeypatch, capsys, damage):
    import os
    import stat
    from dirtside.agent.config import device_path
    home = tmp_path / "device"
    home.mkdir()
    with mounted(tmp_path / "gateway") as (app, reg, *_), listening(app) as url:
        scope = set_hermes_home_override(home)
        try:
            def pair():
                code = reg.mint("laptop", int(time.time()))
                args = parser().parse_args(["dirtside", "pair", url, "--name", "laptop", "--code=" + code])
                assert handle(args) is None
                output = capsys.readouterr().out
                assert code not in output and "old-secret" not in output
                return output
            pair()
            fresh = DeviceConfig.load()
            replace(fresh, policy=replace(fresh.policy, env_passthrough=("OWNER_SOCKET",))).save()
            path = device_path()
            if damage == "unreadable":
                original = os.open
                def unreadable(file, *args, **kwargs):
                    if Path(file) == path:
                        raise PermissionError("old-secret")
                    return original(file, *args, **kwargs)
                monkeypatch.setattr(os, "open", unreadable)
            elif damage == "permissions":
                path.chmod(0o644)
            else:
                path.write_text("old-secret{" if damage == "malformed" else "{}")
            output = pair()
            monkeypatch.undo()
            assert "Existing device configuration could not be read safely; env_passthrough reset to none." in output
            repaired = DeviceConfig.load()
            assert repaired.policy.env_passthrough == ()
            assert repaired.device_id == fresh.device_id and repaired.token != fresh.token
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        finally:
            reset_hermes_home_override(scope)
