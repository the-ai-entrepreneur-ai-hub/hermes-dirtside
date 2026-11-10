"""Retained credentials give the stop answer only after valid signed proof."""
import base64
import json
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from core_rig import Rig
from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from network_support import DESKTOP_TOKEN, mounted, subprocess_agent, until
from notice_support import Clock, gateway, retire

from dirtside.agent.config import DeviceConfig
from dirtside.agent.loop import DEVICE_API, _Agent
from dirtside.protocol import canonical, sign, verify
from test_executor import alive
from test_protocol import result_body
from test_registry import paired, request as exec_request
from test_routes import API, headers, hello
from test_routes import routes as routes


def body_for(kind, key, root, name="device"):
    return {
        "hello": hello(key, root, name),
        "poll": {"running": []},
        "chunk": dict(id="r_" + "ab" * 12, seq=0, data="eA=="),
        "result": result_body(),
    }[kind]


def device_path(kind):
    return API + "/device/" + ("pair" if kind == "hello" else kind)


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


def revoke(client, device):
    response = client.post(API + f"/devices/{device.name}/revoke", headers=headers(DESKTOP_TOKEN))
    assert response.status_code == 200, response.text


def explicit(response):
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "device revoked"}


def generic(response):
    assert response.status_code == 401, response.text
    assert "revoked" not in response.text


@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
def test_revoked_key_gets_explicit_rejection_on_every_route(routes, tmp_path, kind, clock):
    client, registry, relay, _, _ = routes
    device, token, key = paired(registry, tmp_path, now=int(time.time()))
    assert not relay.last_seen
    revoke(client, device)
    wire = sign(key, kind, device.id, body_for(kind, key, tmp_path, device.name))
    explicit(client.post(device_path(kind), headers=headers(token), json=wire))
    assert not relay.last_seen and not relay.handles
    assert not registry.path.with_name("owner.json").exists()


def invalid_wire(kind, key, sender, body, fault):
    signing = SigningKey.generate() if fault == "wrong-signature" else key
    sender = "0" * 32 if fault == "unknown-id" else sender
    wire_kind = ("chunk" if kind == "poll" else "poll") if fault == "wrong-kind" else kind
    wire = sign(signing, wire_kind, sender, body)
    if fault == "stale":
        payload = {name: value for name, value in wire.items() if name != "sig"}
        payload["ts"] -= 301
        wire = payload | {"sig": base64.b64encode(key.sign(canonical(payload)).signature).decode()}
    if fault == "unsigned":
        del wire["sig"]
    return wire


@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
@pytest.mark.parametrize("fault", ["wrong-signature", "unknown-id", "stale", "unsigned",
                                 "wrong-kind", "missing-bearer", "unknown-bearer", "invalid-json"])
def test_invalid_requests_never_get_explicit_stop_answer(routes, tmp_path, kind, fault, clock):
    client, registry, relay, _, _ = routes
    device, token, key = paired(registry, tmp_path, now=int(time.time()))
    revoke(client, device)
    wire = invalid_wire(kind, key, device.id, body_for(kind, key, tmp_path, device.name), fault)
    auth = {} if fault == "missing-bearer" else headers("unknown" if fault == "unknown-bearer" else token)
    payload = {"content": b"{"} if fault == "invalid-json" else {"json": wire}
    generic(client.post(device_path(kind), headers=auth, **payload))
    explicit(client.post(device_path(kind), headers=headers(token),
                         json=sign(key, kind, device.id, body_for(kind, key, tmp_path, device.name))))
    assert not relay.last_seen and not relay.handles


@pytest.mark.parametrize("kind", ["poll", "chunk", "result"])
def test_pre_revoke_signed_request_cannot_be_replayed(routes, tmp_path, kind, clock):
    client, registry, relay, _, _ = routes
    device, token, key = paired(registry, tmp_path, now=int(time.time()))
    handle = relay.submit(exec_request(device))
    body = body_for(kind, key, tmp_path)
    if kind != "poll":
        body["id"] = handle.req.id
    captured = sign(key, kind, device.id, body)
    try:
        assert client.post(device_path(kind), headers=headers(token), json=captured).status_code == 200
        revoke(client, device)
        generic(client.post(device_path(kind), headers=headers(token), json=captured))
        explicit(client.post(device_path(kind), headers=headers(token),
                             json=sign(key, kind, device.id, body)))
    finally:
        handle.kill()
        handle.stdout.close()


@pytest.mark.parametrize("kind", ["poll", "chunk", "result"])
def test_revoked_key_survives_gateway_restart(tmp_path, kind, clock):
    with mounted(tmp_path) as (app, registry, _, _), TestClient(app) as client:
        device, token, key = paired(registry, tmp_path, now=int(time.time()))
        revoke(client, device)
    with mounted(tmp_path) as (app, _, relay, _), TestClient(app) as client:
        assert not relay._revoked
        explicit(client.post(device_path(kind), headers=headers(token),
                             json=sign(key, kind, device.id, body_for(kind, key, tmp_path))))
        assert not relay.last_seen


@pytest.mark.parametrize("revoked_first", [False, True])
def test_repair_keeps_retired_key_separate_from_new_device(routes, tmp_path, revoked_first, clock):
    client, registry, relay, _, _ = routes
    old, old_token, old_key = paired(registry, tmp_path, now=int(time.time()))
    registry.set_target("old-chat", old.id)
    if revoked_first:
        revoke(client, old)
    code = client.post(API + "/pairing", headers=headers(DESKTOP_TOKEN), json={"name": old.name}).json()["code"]
    new_key = SigningKey.generate()
    response = client.post(device_path("hello"), headers=headers(code),
                           json=sign(new_key, "hello", old.name, hello(new_key, tmp_path, old.name)))
    assert response.status_code == 200, response.text
    current, new_token = registry.active_device(old.name), response.json()["token"]
    assert current.id == old.id and current.pubkey == bytes(new_key.verify_key)
    assert registry.device_by_id(old.id) == current and registry.target("old-chat") == old.id
    assert registry.credential_for(old_token, int(time.time())) is None
    retained = type(registry)(registry.path).credential_for(old_token, int(time.time()), include_revoked=True)
    assert retained.pubkey == old.pubkey and retained.id == old.id
    handle = relay.submit(exec_request(current))
    try:
        for kind in ("poll", "chunk", "result"):
            body = body_for(kind, old_key, tmp_path)
            if kind != "poll":
                body["id"] = handle.req.id
            response = client.post(device_path(kind), headers=headers(old_token),
                                   json=sign(old_key, kind, old.id, body))
            explicit(response)
        assert handle.req.id in relay.handles and not relay.tail(handle.req.id) and not relay.last_seen
        assert client.post(device_path("poll"), headers=headers(new_token),
                           json=sign(old_key, "poll", current.id, {})).status_code == 400
        response = client.post(device_path("poll"), headers=headers(new_token),
                               json=sign(new_key, "poll", current.id, {"running": []}))
        assert response.status_code == 200, response.text
        env = verify(SigningKey(registry.relay_seed).verify_key, response.json(), int(time.time()))
        assert env.body["exec"]["id"] == handle.req.id
        body = result_body() | dict(id=handle.req.id, seq=0, data="bmV3")
        assert client.post(device_path("result"), headers=headers(new_token),
                           json=sign(new_key, "result", current.id, body)).status_code == 200
        assert handle.wait(0) == 0 and handle.stdout.read() == b"new"
        assert relay.is_online(current.id)
    finally:
        handle.kill()
        handle.stdout.close()


@pytest.mark.parametrize("kind", ["poll", "chunk", "result"])
def test_revoke_between_lookup_and_verification_does_not_dispatch(routes, tmp_path, monkeypatch, kind, clock):
    client, registry, relay, module, _ = routes
    device, token, key = paired(registry, tmp_path, now=int(time.time()))
    handle = relay.submit(exec_request(device))
    captured, release, original = threading.Event(), threading.Event(), module.verified
    def held(*args):
        captured.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(module, "verified", held)
    body = body_for(kind, key, tmp_path)
    if kind != "poll":
        body["id"] = handle.req.id
    try:
        with ThreadPoolExecutor(1) as pool:
            response = pool.submit(client.post, device_path(kind), headers=headers(token),
                                   json=sign(key, kind, device.id, body))
            try:
                until(captured.is_set, timeout=5)
                assert registry.revoke(device.name, int(time.time())) == device
                assert not relay._revoked
            finally:
                release.set()
            explicit(response.result(timeout=5))
        explicit(client.post(device_path(kind), headers=headers(token),
                             json=sign(key, kind, device.id, body)))
        assert not relay.last_seen and handle.state.value == "queued"
        assert not registry.path.with_name("owner.json").exists()
    finally:
        handle.kill()
        handle.stdout.close()


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("replaced", [False, True])
def test_retired_bearer_never_grants_local_or_dashboard_authority(tmp_path, monkeypatch, public, replaced, clock):
    with gateway(tmp_path, monkeypatch, public) as (app, registry, _, _, _):
        with TestClient(app, client=("127.0.0.1", 10)) as client:
            device, token, _ = paired(registry, tmp_path, now=int(time.time()))
            other, _, _ = paired(registry, tmp_path, name="other", now=int(time.time()))
            assert client.get(API + "/local/devices", headers=headers(registry.local_secret)).status_code == 200
            assert client.get(API + "/devices", headers=headers(DESKTOP_TOKEN)).status_code == 200
            if replaced:
                retire(registry, device, tmp_path, clock, True)
            else:
                revoke(client, device)
            for method, path in (("POST", "/local/exec"), ("POST", "/local/kill?id=bad"),
                                 ("GET", "/local/stream?id=bad"), ("GET", "/local/devices"),
                                 ("GET", "/local/requests"), ("POST", "/device/pair"),
                                 ("GET", "/devices"), ("POST", "/pairing"),
                                 ("POST", "/devices/other/revoke"), ("POST", "/local/devices")):
                payload = {"device_id": other.id} if path == "/local/devices" else {"name": "other"}
                generic(client.request(method, API + path, json=payload))
                generic(client.request(method, API + path, headers=headers(token), json=payload))
            assert registry.recent(10) == [] and registry.active_device("other") == other


def activity_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_offline_revoked_agent_stops_without_parked_poll(tmp_path):
    with Rig(tmp_path) as rig:
        rig.pair()
        assert rig.agent is None and not rig.online()
        cfg = DeviceConfig.load(rig.device_home / "dirtside/device.json")
        assert rig.core.http("POST", f"/devices/{rig.name}/revoke").status_code == 200
        late = tmp_path / "late"
        with subprocess_agent(cfg, late) as proc:
            until(lambda: any(row["event"] == "revoked"
                              for row in activity_events(late / "dirtside/agent.log")), timeout=5)
            assert proc.wait(timeout=5) == 0
        events = [row["event"] for row in activity_events(late / "dirtside/agent.log")]
        assert events[-2:] == ["revoked", "stopped"] and all(event == "poll-error" for event in events[:-2])


@pytest.mark.parametrize("kind", ["chunk", "result"])
@pytest.mark.parametrize("skew", [-60, 0, 60])
def test_real_agent_upload_stops_without_an_open_poll(tmp_path, monkeypatch, kind, skew):
    from notice_support import envelope
    monkeypatch.setattr("dirtside.agent.loop.sign", lambda key, kind, sender, body:
                        envelope(key, kind, sender, body, int(time.time()) + skew))
    with Rig(tmp_path) as rig:
        rig.pair()
        cfg = DeviceConfig.load(rig.device_home / "dirtside/device.json")
        marker, release = tmp_path / "started", tmp_path / "release"
        script = (f"echo $$ > {shlex.quote(str(marker))}; "
                  f"while [ ! -e {shlex.quote(str(release))} ]; do sleep 0.01; done; printf output")
        script += "; sleep 60" if kind == "chunk" else ""
        rig.core.call("queue", name=rig.name, command="printf output", script=script)
        responses, events, stop = [], [], threading.Event()
        def observed(response):
            if response.request.url.path.endswith("/" + kind):
                response.read()
                responses.append((response.status_code, response.json()))
        with httpx.Client(base_url=rig.core.url + "/", headers=headers(cfg.token), trust_env=False,
                          event_hooks={"response": [observed]}) as client:
            agent = _Agent(cfg, client, stop, SimpleNamespace(write=lambda event, **_: events.append(event)))
            try:
                response = client.post(DEVICE_API + "poll", json=sign(cfg.key, "poll", cfg.device_id, {}))
                assert response.status_code == 200, response.text
                agent.dispatch(response.json())
                until(marker.exists, timeout=5)
                assert rig.agent is None
                assert rig.core.http("POST", f"/devices/{rig.name}/revoke").status_code == 200
                release.touch()
                until(lambda: responses, timeout=5)
                assert responses[0] == (401, {"detail": "device revoked"})
                until(stop.is_set, timeout=5)
            finally:
                release.touch()
                agent.shutdown()
                agent.pool.shutdown(wait=True)
            assert responses == [(401, {"detail": "device revoked"})]
            assert not agent.running and not alive(int(marker.read_text()))
            assert events == ["contact", "started", "finished"] or events == ["started", "contact", "finished"]
