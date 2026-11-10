"""Upgrade, retired queues and retained mounted-method generations."""
import json
import os
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from core_rig import Core, Rig, until
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth.registry import (
    register_global_provider, restore_registration, snapshot_registration,
)
from nacl.signing import SigningKey
from network_support import mounted
from route_support import plugin_context, register

from dirtside.auth import DirtsideDeviceAuth
from dirtside.protocol import sign
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired, request
from test_review_name_safety import pair_as
from test_routes import API, headers, hello


@pytest.mark.parametrize("action", ["reload", "duplicate", "profile"])
def test_real_loader_registration_keeps_launch_routes_and_status_working(tmp_path, action):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        before = rig.core.http("GET", "/devices").json()
        assert rig.core.terminal("printf before")["output"] == "before"
        result = rig.core.call("registration", action=action)
        assert result["enabled"] and result["reason"] == "", result
        assert result["registrations"] == 9 and result["all_active"], result
        assert result["replaced"] is (action == "reload"), result
        assert result["old_enabled"] is (action != "reload"), result
        status = rig.core.call("slash", raw_args="")
        assert "disabled" not in status and rig.name in status, status
        assert rig.core.http("GET", "/devices").json()[0]["id"] == before[0]["id"]
        secret = Path(rig.core.info["registry"]).with_name("local.secret").read_text()
        assert rig.core.http("GET", "/local/devices", authenticated=False,
                             headers=headers(secret)).status_code == 200
        key = SigningKey(bytes.fromhex(rig.config["key"]))
        poll = rig.core.http("POST", "/device/poll", authenticated=False,
                             headers=headers(rig.config["token"]),
                             json=sign(key, "poll", rig.config["device_id"], {"running": ["r_" + "ab" * 12]}))
        assert poll.status_code == 200, poll.text
        assert rig.core.terminal("printf after")["output"] == "after"
        assert rig.agent.poll() is None
        if action == "duplicate":
            result = rig.core.call("reload")
            assert result == {"replaced": True, "old_enabled": False, "enabled": True}
            assert rig.core.terminal("printf reloaded")["output"] == "reloaded"


@pytest.mark.parametrize("marker", [None, 0, "1"])
def test_upgrade_from_unmarked_provider_starts_fresh_runtime(tmp_path, monkeypatch, marker):
    registry = Registry(tmp_path / "data.db")
    relay = Relay(registry)
    del relay.access
    old = DirtsideDeviceAuth(registry, relay)
    if marker is not None:
        old.runtime_version = marker
    previous = snapshot_registration("dirtside")
    register_global_provider(old)
    try:
        with plugin_context() as ctx:
            current = register(ctx, tmp_path, monkeypatch)
            assert current.routes.enabled and current.runtime_version == 2
            assert current.registry.path == old.registry.path
            assert current.relay is not old.relay
            assert current.environment_provider._relay is current.relay
            assert callable(current.tool_execution)
    finally:
        restore_registration("dirtside", old, previous)


@pytest.mark.parametrize("version", [1, 2])
def test_reload_refreshes_v1_lookup_and_keeps_v2_runtime(tmp_path, monkeypatch, version):
    with plugin_context() as ctx:
        old = register(ctx, tmp_path, monkeypatch)
        device, token, key = paired(old.registry, tmp_path, now=int(time.time()))
        with mounted(tmp_path, relay=old.relay, provider=old) as (app, *_), TestClient(app) as web:
            def poll():
                return web.post(API + "/device/poll", headers=headers(token),
                                json=sign(key, "poll", device.id, {"running": ["r_" + "ab" * 12]}))
            assert web.post(API + "/device/poll", json={}).status_code == 401
            assert poll().status_code == 200
            original = old.registry
            if version == 1:
                class PriorRegistry:
                    path = original.path
                    def __getattr__(self, name):
                        return getattr(original, name)
                    def credential_for(self, token, now):
                        return original.credential_for(token, now)
                old.registry = PriorRegistry()
            old.runtime_version = version
            ctx._manager.unload()
            current = register(ctx, tmp_path, monkeypatch)
            old.routes.dispose()
            assert poll().status_code == 200
            assert current.routes.enabled and current.runtime_version == 2
            assert (current.registry is original) is (version == 2)
            assert (current.relay is old.relay) is (version == 2)


def test_unloaded_owner_relay_uses_client_not_retired_queue(tmp_path, monkeypatch):
    with plugin_context() as ctx:
        provider = register(ctx, tmp_path, monkeypatch)
        provider.relay._owner_pid = os.getpid()
        assert provider.relay.connection() is provider.relay
        provider.routes.dispose()
        assert provider.relay.connection() is provider.relay._client


@pytest.mark.parametrize("transport", ["in-process", "client"])
def test_cached_conversation_survives_disable_enable(tmp_path, transport):
    with Rig(tmp_path / "rig") as rig, ExitStack() as stack:
        rig.pair().start_agent().choose()
        core = stack.enter_context(Core(rig.core.home, env=rig.core.env, worker=True)) if transport == "client" else rig.core
        assert core.terminal("printf before", timeout=20)["output"] == "before"
        identity = core.call("state", session="chat")["identity"]
        assert identity is not None
        disabled_at = time.time()
        assert not rig.core.call("reload", enabled=False)["enabled"]
        rejected = rig.core.http("POST", "/device/poll", authenticated=False,
                                 headers=headers(rig.config["token"]), json={})
        assert rejected.status_code == 401
        assert rejected.json() == {"error": "session_expired", "detail": "Unauthorized",
                                   "reason": "invalid_or_expired_session", "login_url": "/login"}
        activity = rig.device_home / "dirtside" / "agent.log"
        until(lambda: any('"event": "poll-error"' in line or '"event": "revoked"' in line
                          for line in activity.read_text().splitlines()
                          if float(json.loads(line)["time"]) >= disabled_at), timeout=5)
        assert rig.agent.poll() is None, activity.read_text()
        assert '"event": "revoked"' not in activity.read_text()
        owner = Path(rig.core.info["registry"]).with_name("owner.json")
        previous_claim = owner.stat().st_mtime_ns
        assert rig.core.call("reload", enabled=True)["enabled"]
        until(lambda: owner.stat().st_mtime_ns > previous_claim, timeout=8)
        assert rig.online(since=disabled_at)
        result = core.terminal("printf after", timeout=20)
        assert result["exit_code"] == 0 and result["output"] == "after", result
        assert core.call("state", session="chat")["identity"] == identity
        rows = rig.core.http("GET", "/requests").json()
        assert any(row["preview"] == "printf after" and row["state"] == "finished" for row in rows)
        assert rig.agent.poll() is None


@pytest.mark.parametrize("operation", ["close", "kill"])
def test_mounted_generations_close_and_kill_after_reload(tmp_path, operation):
    with Core(tmp_path / "gateway") as core:
        core.call("reload", enabled=False)
        core.call("reload", enabled=True)
        for generation in range(2):
            if generation:
                core.call("reload")
            if operation == "close":
                assert core.call("generation")["close"]
                continue
            root = tmp_path / f"device-{generation}"
            root.mkdir()
            name = f"device-{generation}"
            core.call("fake_device", name=name, root=str(root))
            queued = core.call("queue", name=name, command="sleep 60", script="sleep 60")
            secret = Path(core.info["registry"]).with_name("local.secret").read_text()
            response = core.http("POST", "/local/kill", authenticated=False,
                                 headers=headers(secret), params={"id": queued["id"]}, json={})
            assert response.status_code == 200, response.text
            assert response.json() == {"cancelled": True}
            rows = core.http("GET", "/requests").json()
            assert next(row for row in rows if row["id"] == queued["id"])["state"] == "cancelled"


@pytest.mark.parametrize("path,method", [("/local/devices", "GET"), ("/local/requests", "GET"),
                                      ("/local/devices", "POST")])
def test_unclaimed_local_owner_fails_fast(tmp_path, path, method):
    with Core(tmp_path / "gateway") as core:
        device_root = tmp_path / "device"
        device_root.mkdir()
        paired = core.call("fake_device", root=str(device_root))
        core.call("reload", enabled=False)
        core.call("reload", enabled=True)
        secret = Path(core.info["registry"]).with_name("local.secret").read_text()
        response = core.http(method, path, authenticated=False, headers=headers(secret),
                             json={"device_id": paired["device_id"]} if method == "POST" else None, timeout=1)
        assert response.status_code == 409, response.text


@pytest.mark.parametrize("new_owner", ["local", "telegram:bob"])
def test_cross_owner_pairing_cancels_live_requests(tmp_path, new_owner):
    with mounted(tmp_path) as (app, registry, relay, _), TestClient(app) as web:
        device, token, _ = pair_as(registry, relay, tmp_path, "telegram:bob")
        relay._owner_pid = os.getpid()
        relay.touch(device.id)
        handles = [relay.submit(request(device, n=n)) for n in (1, 2)]
        try:
            relay.next(device.id, 0)
            assert {handle.state.value for handle in handles} == {"queued", "running"}
            code = registry.mint(device.name, int(time.time()), owner=new_owner, privileged=True)
            key = SigningKey.generate()
            invalid = web.post(API + "/device/pair", headers=headers(code), content=b"{")
            assert invalid.status_code == 400
            assert all(not handle._done.is_set() for handle in handles)
            response = web.post(API + "/device/pair", headers=headers(code),
                                json=sign(key, "hello", device.name, hello(key, tmp_path, device.name)))
            assert response.status_code == 200, response.text
            replacement = registry.active_device(device.name)
            if new_owner == "telegram:bob":
                assert replacement.id == device.id
                assert all(not handle._done.is_set() for handle in handles)
            else:
                assert replacement.id != device.id and registry.device_by_id(device.id) is None
                assert registry.credential_for(token, int(time.time())) is None
                assert all(handle._done.is_set() for handle in handles)
                assert all(handle.state.value == "cancelled" and handle.wait(0) == 130 for handle in handles)
                assert not relay.is_online(device.id)
                assert relay._paired_keys[replacement.id] == replacement.pubkey
        finally:
            for handle in handles:
                handle.kill()
                handle.stdout.close()
