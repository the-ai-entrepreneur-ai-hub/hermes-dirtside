"""Mounted routers follow real rediscovery and remain closed when disabled."""
import shlex
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from core_rig import Core, Rig, until
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth.registry import register_global_provider
from nacl.signing import SigningKey, VerifyKey
from network_support import mounted

from dirtside.protocol import sign, verify
from test_review_device_owners_core import as_user, owned_pair
from test_review_token_routes import PublicContext, credentials, endpoints, register, request, stale_outer_routes


def device_and_local_calls(rig):
    cfg = rig.config
    key = SigningKey(bytes.fromhex(cfg["key"]))
    poll = rig.core.http("POST", "/device/poll", authenticated=False,
                         headers={"Authorization": "Bearer " + cfg["token"]},
                         json=sign(key, "poll", cfg["device_id"], {}))
    assert poll.status_code == 200, poll.text
    verify(VerifyKey(bytes.fromhex(cfg["relay_pubkey"])), poll.json(), int(time.time()))
    secret = Path(rig.core.info["registry"]).with_name("local.secret").read_text()
    local = rig.core.http("GET", "/local/devices", authenticated=False,
                          headers={"Authorization": "Bearer " + secret})
    assert local.status_code == 200
    assert any(row["id"] == cfg["device_id"] for row in local.json())


@pytest.mark.parametrize("transport", ["in-process", "client"])
def test_force_rediscovery_keeps_device_and_local_calls_working(tmp_path, transport):
    with Rig(tmp_path / "rig") as rig, ExitStack() as stack:
        rig.pair().start_agent().choose()
        core = stack.enter_context(Core(rig.core.home, env=rig.core.env, worker=True)) if transport == "client" else rig.core
        if core is not rig.core:
            core.call("target", session="chat", name=rig.name)
        assert core.terminal("printf before")["output"] == "before"
        release = tmp_path / "release"
        command = f"printf started; while ! test -f {shlex.quote(str(release))}; do sleep 0.05; done; printf done"
        pending = core.submit("terminal", session="chat", args={"command": command, "timeout": 60})
        try:
            row = until(lambda: next((row for row in rig.core.http("GET", "/requests").json()
                                      if row["preview"] == command[:120] and row["state"] == "running"), None))
            if transport == "client":
                until(lambda: rig.core.call("stream_attached", request_id=row["id"]))
            reloaded = rig.core.call("reload")
            assert reloaded["replaced"] and not reloaded["old_enabled"] and reloaded["enabled"]
            release.touch()
            device_and_local_calls(rig)
            result = pending.result(timeout=65)
            assert result["exit_code"] == 0 and result["output"] == "starteddone", result
            result = core.terminal("printf after")
            assert result["exit_code"] == 0 and result["output"] == "after", result
            rows = rig.core.http("GET", "/requests").json()
            assert any(row["preview"] == "printf after" for row in rows)
        finally:
            release.touch()


def test_disabled_then_reenabled_plugin_reuses_mounted_router(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent()
        def configure(action):
            return rig.core.call("reload", enabled=action == "enable")
        assert not configure("disable")["enabled"]
        for path, method, _ in endpoints():
            response = rig.core.http(method, path.removeprefix("/api/plugins/dirtside"),
                                     params={"id": "r_" + "0" * 24}, json={})
            assert response.status_code in {401, 404}, (path, response.status_code, response.text)
        assert configure("enable")["enabled"]
        device_and_local_calls(rig)


@pytest.mark.parametrize("gate", [False, True])
def test_mounted_router_uses_replacement_registry_and_refuses_failed_instance(tmp_path, monkeypatch, gate):
    stale_outer_routes()
    first = register(PublicContext(), tmp_path / "first", monkeypatch)
    old_creds, _ = credentials(first, tmp_path)
    with mounted(tmp_path, gate=gate, relay=first.relay, provider=first) as (app, *_):
        try:
            with TestClient(app, client=("127.0.0.1", 10)) as web:
                assert request(web, "GET", "/api/plugins/dirtside/local/devices", old_creds["local"]).status_code == 200
                second = register(PublicContext(), tmp_path / "second", monkeypatch)
                new_creds, _ = credentials(second, tmp_path)
                register_global_provider(second)
                first.routes.dispose()
                assert request(web, "GET", "/api/plugins/dirtside/local/devices", new_creds["local"]).status_code == 200
                assert request(web, "GET", "/api/plugins/dirtside/local/devices", old_creds["local"]).status_code == 401
                bad = register(PublicContext(3, "none"), tmp_path / "bad", monkeypatch)
                bad_creds, _ = credentials(bad, tmp_path)
                register_global_provider(bad)
                for path, method, kind in endpoints():
                    assert request(web, method, path, bad_creds[kind]).status_code == 401
        finally:
            register_global_provider(first)


def test_frozen_group_prompt_disclosure_matches_core(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        owned_pair(rig, "A")
        as_user(rig.core, "slash", "A", raw_args="use " + rig.name)
        first = as_user(rig.core, "prompt", "A")
        later = as_user(rig.core, "prompt", "B")
        assert later == first and rig.name in str(later) and rig.device_env["HOME"] in str(later)
        result = as_user(rig.core, "terminal", "B", args={"command": "printf forbidden"})
        assert result["exit_code"] != 0
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        assert "Every authorized turn's fact line stays in conversation history, not just the first frozen render." in readme
        assert "Other participants can receive the device name, OS and home from those lines and the frozen section" in readme
        assert "including stale facts and online state, even when their own device calls are denied." in readme
        assert "`/land` and `/dirtside use` replies also show the home to the whole chat." in readme


def test_server_execution_limit_is_explicit(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        owned_pair(rig, "A")
        secret_path = Path(rig.core.info["registry"]).with_name("local.secret")
        result = as_user(rig.core, "terminal", "B", session="server-thread",
                         args={"command": "cat " + shlex.quote(str(secret_path))})
        assert result["exit_code"] == 0
        secret = result["output"].strip()
        response = rig.core.http("GET", "/local/devices", authenticated=False,
                                 headers={"Authorization": "Bearer " + secret})
        assert response.status_code == 200 and any(row["name"] == rig.name for row in response.json())
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        assert "Server-target execution is gateway-user execution" in readme
        assert "approvals and allowlists" in readme
