"""Provider liveness at real loader teardown and closed-owner replies."""
import secrets
import time

import pytest
from core_rig import Core, Rig, install
from gateway.session_context import clear_session_vars, set_session_vars
from route_support import MissingMethodContext, plugin_context, record_routes, register

from dirtside.commands import Commands
from dirtside.environment import EnvironmentConnectionError, require_online
from dirtside.shortcuts import Shortcuts
from test_registry import paired


@pytest.mark.parametrize("kind", ["device", "pair", "local", "retained"])
def test_targeted_unload_rejects_credentials_before_provider_removal(tmp_path, kind):
    home = tmp_path / "gateway"
    env = install(home)
    env["HERMES_DASHBOARD_DRAIN_SECRET"] = secrets.token_urlsafe(32)
    with Core(home, env=env) as core:
        result = core.call("registration", action="targeted")
        assert result["registered"] and result["enabled"]
        assert len(result["active"]) == 9 and not any(result["active"])
        assert result["bound"] == 0 and result["removed"] and result["closed"]
        assert result[kind] == {"status": 401, "recognized": False}


@pytest.mark.parametrize("closed", ["missing", "refused", "unloaded"])
def test_authorized_device_replies_explain_closure(tmp_path, monkeypatch, closed):
    with plugin_context() as ctx:
        original = ctx.get_config
        monkeypatch.setattr(ctx, "get_config", lambda key, default=None:
                            ["telegram:alice"] if key == "owners" else original(key, default))
        if closed == "refused":
            record_routes(ctx, monkeypatch, 5, "none")
        provider = register(MissingMethodContext(ctx) if closed == "missing" else ctx, tmp_path, monkeypatch)
        device, *_ = paired(provider.registry, tmp_path, now=int(time.time()))
        if closed == "unloaded":
            ctx._manager.unload()
        commands = Commands(ctx, provider.registry, provider.relay, access=provider.relay.access)
        tokens = set_session_vars(session_key="closure", session_id="closure", platform="telegram", user_id="alice")
        try:
            reason = provider.routes.reason
            with pytest.raises(EnvironmentConnectionError) as error:
                require_online(device, provider.relay)
            assert reason in str(error.value) and "offline" not in str(error.value)
            assert "dirtside-agent serve" not in error.value.retry_hint
            assert "hermes dirtside serve" not in error.value.retry_hint
            assert commands("use " + device.name) == reason
            assert Shortcuts(commands).land(device.name) == reason
            assert commands("use") == reason and commands("devices") == reason
            assert "now targets server" in commands("use server")
            set_session_vars(session_key="closure", session_id="closure", platform="telegram", user_id="mallory")
            assert commands("devices") == "No devices are paired."
            assert commands("use " + device.name) == f"Device '{device.name}' is not paired; the target was not changed."
            assert commands("") == "This conversation targets server. Online devices: none. Sender: telegram:mallory."
            with pytest.raises(EnvironmentConnectionError, match="offline") as error:
                require_online(device, provider.relay)
            assert "dirtside-agent serve" in error.value.retry_hint
        finally:
            clear_session_vars(tokens)


def test_refused_reload_keeps_owner_commands_local_and_truthful(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        assert rig.core.terminal("printf before")["output"] == "before"
        queued = rig.core.call("queue", name=rig.name, command="sleep 60", script="sleep 60")
        result = rig.core.call("registration", action="refuse")
        assert result["owner_pid"] and result["local_origin"] is None
        reason = result["reason"]
        actor = dict(session="chat", platform="telegram", user_id="alice")
        for command, raw in (("dirtside", ""), ("dirtside", "devices"), ("dirtside", "use"),
                             ("dirtside", "use laptop"), ("land", "laptop")):
            assert rig.core.call("slash", command=command, raw_args=raw, **actor) == reason
        marker = tmp_path / "must-not-run"
        terminal = rig.core.call("terminal", args={"command": f"printf forbidden > '{marker}'"}, **actor)
        assert reason in str(terminal) and not marker.exists()
        assert "dirtside-agent serve" not in str(terminal) and "hermes dirtside serve" not in str(terminal)
        mallory = dict(actor, user_id="mallory")
        assert rig.core.call("slash", raw_args="", **mallory) == (
            "This conversation targets an unpaired device. Online devices: none. Sender: telegram:mallory.")
        assert rig.core.call("slash", raw_args="devices", **mallory) == "No devices are paired."
        assert rig.core.call("slash", raw_args="revoke laptop", **actor) == "Revoked laptop and cancelled its live requests."
        state = rig.core.call("registration", action="state", device_id=rig.config["device_id"])
        assert state["revoked"] and state["rows"][queued["id"]] == "cancelled"
        assert rig.core.call("slash", raw_args="revoke laptop", **actor) == (
            "No paired device named 'laptop' was found; any pending pairing code was revoked.")
