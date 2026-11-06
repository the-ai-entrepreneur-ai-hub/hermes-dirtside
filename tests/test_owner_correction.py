"""Device traffic, not mounting a server, determines the shared relay owner."""
import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import httpx
import psutil
import pytest
from core_rig import Core, until
from fastapi.testclient import TestClient
from gateway.session_context import clear_session_vars, set_session_vars
from network_support import listening, mounted

from dirtside.client import Client, OWNER_MISSING
from dirtside.commands import Commands
from dirtside.environment import DirtsideEnvironment, EnvironmentConnectionError
from dirtside.local import PREFIX
from dirtside.prompt import TargetPrompt
from dirtside.protocol import sign
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired, request
from test_protocol import result_body
from test_routes import API, headers, hello


def recorded(registry, *, pid=None, origin="http://127.0.0.1:1", started=None):
    data = dict(pid=os.getpid() if pid is None else pid, origin=origin,
                started=int(psutil.Process().create_time()) if started is None else started)
    registry.path.with_name("owner.json").write_text(json.dumps(data))


def test_only_device_traffic_earns_ownership(tmp_path):
    relay = Relay(Registry(tmp_path / "data.db"))
    relay._client = client = Client(relay)
    try:
        with mounted(tmp_path, gate=False, relay=relay) as (app, registry, _, _):
            device, token, key = paired(registry, tmp_path)
            path = registry.path.with_name("owner.json")
            with TestClient(app, client=("127.0.0.1", 10)) as web:
                assert relay._owner_pid is None and relay.connection() is client
                assert web.get(API + "/devices").json()[0]["online"] is False
                assert web.get(API + "/requests").json() == []
                assert web.get(PREFIX + "/devices", headers=headers(registry.local_secret)).status_code == 200
                auth = headers(registry.local_secret)
                assert web.get(PREFIX + "/requests", headers=auth).json() == []
                req = request(device)
                assert web.post(PREFIX + "/exec", headers=auth, json=asdict(req)).status_code == 409
                assert web.get(PREFIX + "/stream", params={"id": req.id}, headers=auth).status_code == 409
                assert web.post(PREFIX + "/kill", params={"id": req.id}, headers=auth, json={}).status_code == 409
                assert web.post(PREFIX + "/devices", headers=auth, json={"device_id": device.id}).status_code == 200
                assert not relay.handles and registry.recent(10) == []
                assert web.post(API + "/pairing", json={"name": "pending"}).status_code == 200
                assert web.put(API + "/sessions/test/target", json={"target": device.name}).status_code == 200
                assert web.get(API + "/sessions/test/target").json() == {"target": device.name}
                assert web.post(API + "/devices/pending/revoke").status_code == 200
                assert not path.exists() and relay._owner_pid is None
                body = dict(id="r_" + "a" * 24, seq=0, data="")
                assert web.post(API + "/device/chunk", headers=headers(token),
                                json=sign(key, "chunk", device.id, body)).status_code == 410
                assert path.exists() and relay._owner_pid == os.getpid()
                assert relay.connection() is relay and relay.is_online(device.id)
    finally:
        client.http.close()


@pytest.mark.parametrize("state", ["absent", "dead", "reused"])
def test_no_live_owner_is_offline_everywhere(tmp_path, state):
    relay = Relay(Registry(tmp_path / "data.db"))
    relay._client = client = Client(relay)
    registry = relay.registry
    device, _, _ = paired(registry, tmp_path)
    registry.set_target("offline-test", device.id)
    if state == "dead":
        recorded(registry, pid=2147483647)
    if state == "reused":
        recorded(registry, started=1)
    tokens = set_session_vars(session_key="offline-test")
    try:
        with mounted(tmp_path, gate=False, relay=relay) as (app, *_), TestClient(app) as web:
            commands = Commands(SimpleNamespace(), registry, relay)
            assert commands("devices") == "Paired devices: macbook (macOS, offline)."
            assert commands("") == "This conversation targets macbook (macOS, offline). Online devices: none."
            assert "(offline, data)" in TargetPrompt(registry, relay).current_target_section({})
            assert web.get(API + "/devices").json() == [
                dict(id=device.id, name=device.name, online=False, os=device.os, home=device.home, last_seen=None)]
            assert relay.connection().is_online(device.id) is False
            env = DirtsideEnvironment(relay, device, "offline-test", "offline", str(tmp_path), 120)
            with pytest.raises(EnvironmentConnectionError) as error:
                env.execute("touch must-not-run")
            assert str(error.value) == (
                "Dirtside: device 'macbook' is offline. Nothing was run on the server.")
            assert not (tmp_path / "must-not-run").exists() and registry.recent(10) == []
    finally:
        clear_session_vars(tokens)
        client.http.close()


def test_second_real_server_imports_core_and_uses_polled_owner(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with Core(tmp_path / "home", user_home=work) as owner:
        owner.call("fake_device", root=str(work))
        path = Path(owner.info["registry"]).with_name("owner.json")
        before = path.read_bytes()
        assert owner.call("info")["owner_pid"] == owner.proc.pid
        with Core(owner.home, env=owner.env) as secondary:
            assert secondary.info["router_mounted"] and secondary.info["owner_pid"] is None
            assert secondary.proc.pid != owner.proc.pid
            assert path.read_bytes() == before
            assert secondary.http("GET", "/devices").json()[0]["online"]
            secondary.call("target", session="secondary", name="fake")
            for raw in ("devices", "", "use fake"):
                assert "online" in secondary.call("slash", session="secondary", raw_args=raw)
            assert "online" in secondary.call("prompt", session="secondary")[0]
            assert secondary.terminal("pwd", session="secondary")["output"] == str(work.resolve())
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(secondary.terminal, "printf live-tail; sleep 60", session="secondary")
                rows = until(lambda: [r for r in owner.http("GET", "/requests").json()
                                      if r["tail"] == "live-tail"])
                other = secondary.http("GET", "/requests", params={"session_key": "secondary"}).json()
                assert next(r for r in other if r["id"] == rows[0]["id"]) == rows[0]
                assert secondary.http("POST", "/devices/fake/revoke").status_code == 200
                assert future.result(4)["exit_code"] == 130
            assert path.read_bytes() == before and secondary.call("info")["owner_pid"] is None
            assert next(r for r in owner.http("GET", "/requests").json()
                        if r["id"] == rows[0]["id"])["state"] == "cancelled"


@pytest.mark.parametrize("host,only", [("0.0.0.0", None), ("::", False), ("::", True)])
def test_real_wildcard_listener_publishes_reachable_loopback(tmp_path, host, only, record_property):
    if host == "::":
        probe = socket.socket(socket.AF_INET6)
        try:
            probe.bind(("::1", 0))
        except OSError as exc:
            record_property("ipv6_unavailable", str(exc))
            return
        finally:
            probe.close()
        connect = "::1"
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            connect = probe.getsockname()[0]
        assert connect != "0.0.0.0"
    with mounted(tmp_path, gate=False) as (app, registry, relay, _):
        device, token, key = paired(registry, tmp_path)
        with listening(app, host=host, ipv6_only=only, connect_host=connect) as url:
            body = dict(id="r_" + "a" * 24, seq=0, data="")
            response = httpx.post(url + API + "/device/chunk", headers=headers(token),
                                  json=sign(key, "chunk", device.id, body), trust_env=False)
            assert response.status_code == 410
            data = json.loads(registry.path.with_name("owner.json").read_text())
            expected = "[::1]" if only else "127.0.0.1"
            assert data["origin"] == f"http://{expected}:{httpx.URL(url).port}"
            client = Client(Relay(registry))
            try:
                assert client.is_online(device.id)
            finally:
                client.http.close()
            assert relay.is_online(device.id)
            changed = registry.path.with_name("owner.json").stat().st_mtime_ns
            response = httpx.post(data["origin"] + API + "/device/chunk", headers=headers(token),
                                  json=sign(key, "chunk", device.id, body), trust_env=False)
            assert response.status_code == 410
            assert registry.path.with_name("owner.json").stat().st_mtime_ns == changed


def test_live_owner_transport_error_is_text_and_use_does_not_mutate(tmp_path):
    registry = Registry(tmp_path / "data.db")
    device, _, _ = paired(registry, tmp_path)
    relay = Relay(registry)
    relay._client = client = Client(relay)
    recorded(registry)
    tokens = set_session_vars(session_key="failed-use")
    try:
        commands = Commands(SimpleNamespace(), registry, relay)
        assert commands("") == OWNER_MISSING
        assert commands("use macbook") == OWNER_MISSING
        assert registry.target("failed-use") is None
        with pytest.raises(EnvironmentConnectionError, match=OWNER_MISSING):
            relay.connection().is_online(device.id)
        with mounted(tmp_path, gate=False, relay=relay) as (app, *_), TestClient(app) as web:
            response = web.get(API + "/devices")
            assert response.status_code == 503 and response.json() == {"detail": OWNER_MISSING}
            assert relay._owner_pid is None
    finally:
        clear_session_vars(tokens)
        client.http.close()


@pytest.mark.parametrize("kind", ["pair", "poll", "chunk", "result"])
def test_each_device_route_can_first_earn_ownership(tmp_path, monkeypatch, kind):
    with mounted(tmp_path) as (app, registry, relay, module):
        monkeypatch.setattr(module.model, "POLL_HOLD_S", 0)
        device, token, key = paired(registry, tmp_path, now=int(module.time.time()))
        sender, message, body = device.id, kind, {}
        if kind == "pair":
            sender, message = "pending", "hello"
            token = registry.mint(sender, int(module.time.time()))
            body = hello(key, tmp_path, sender)
        elif kind == "chunk":
            body = dict(id="r_" + "a" * 24, seq=0, data="")
        elif kind == "result":
            body = result_body()
        with TestClient(app, base_url="http://127.0.0.1:1234") as client:
            path = registry.path.with_name("owner.json")
            assert not path.exists() and relay._owner_pid is None
            assert client.post(API + "/device/" + kind,
                               headers=headers(token), json=sign(key, message, sender, body)).status_code == (
                                   200 if kind in {"pair", "poll"} else 410)
            assert path.exists() and relay._owner_pid == os.getpid()
