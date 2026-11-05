"""Production discovery, auth gates and route ordering with real core imports."""
import base64
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey, VerifyKey
from network_support import DESKTOP_TOKEN, mounted, until

from dirtside.model import Pending, RequestState
from dirtside.protocol import parse_hello, sign, verify
from test_protocol import result_body
from test_registry import paired, request

API = "/api/plugins/dirtside"


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def hello(key, root, name="device"):
    return dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name=name, os="test",
                arch="arm64", home=str(root), temp_dir=str(root), agent_version="0.1.0")


@pytest.fixture(params=[False, True], ids=["gate-off", "gate-on"])
def routes(tmp_path, request):
    with mounted(tmp_path, gate=request.param) as (app, reg, relay, module):
        with TestClient(app) as client:
            yield client, reg, relay, module, request.param


def test_route_order_and_pairing(routes, tmp_path):
    client, reg, relay, _, _ = routes
    now, key = int(time.time()), SigningKey.generate()
    code = reg.mint("device", now)
    body = hello(key, tmp_path)
    wire = sign(key, "hello", "device", body)
    assert client.post(API + "/device/pair", headers=headers("wrong"), content=b"{").status_code == 401
    assert client.post(API + "/device/pair", headers=headers(code), json=wire | {"sig": "!"}).status_code == 400
    assert isinstance(reg.credential_for(code, now), Pending) and not relay.last_seen
    for kind in ("poll", "chunk", "result"):
        assert client.post(API + "/device/" + kind, headers=headers(code), content=b"{").status_code == 401
    expired = reg.mint("expired", now - 601)
    assert client.post(API + "/device/pair", headers=headers(expired), content=b"{").status_code == 401
    response = client.post(API + "/device/pair", headers=headers(code), json=wire)
    assert response.status_code == 200
    data, device = response.json(), reg.active_device("device")
    assert data["device_id"] == device.id and reg.credential_for(data["token"], now) == device
    assert base64.b64decode(data["relay_pubkey"]) == bytes(SigningKey(reg.relay_seed).verify_key)
    assert client.post(API + "/device/pair", headers=headers(code), json=wire).status_code == 401
    assert client.post(API + "/device/pair", headers=headers(data["token"]), json=wire).status_code == 401
    assert not relay.is_online(device.id)
    bad = sign(SigningKey.generate(), "poll", device.id, {})
    assert client.post(API + "/device/poll", headers=headers(data["token"]), json=bad).status_code == 400
    assert not relay.is_online(device.id)
    wrong_sender = sign(key, "poll", "other", {})
    assert client.post(API + "/device/poll", headers=headers(data["token"]), json=wrong_sender).status_code == 400
    assert not relay.is_online(device.id)
    malformed = sign(key, "chunk", device.id, {"id": "invalid"})
    assert client.post(API + "/device/chunk", headers=headers(data["token"]), json=malformed).status_code == 400
    assert relay.is_online(device.id)


def test_chunk_replay_inline_result_and_late_result(routes, tmp_path):
    client, reg, relay, _, _ = routes
    device, token, key = paired(reg, tmp_path, now=int(time.time()))
    handle = relay.submit(request(device))
    relay.next(device.id, 0)
    chunk = sign(key, "chunk", device.id, dict(id=handle.req.id, seq=0, data="YWJj"))
    for _ in range(2):
        assert client.post(API + "/device/chunk", headers=headers(token), json=chunk).status_code == 200
    body = result_body() | dict(id=handle.req.id, seq=1, data="ZGVm")
    wire = sign(key, "result", device.id, body)
    assert client.post(API + "/device/result", headers=headers(token), json=wire).status_code == 200
    assert handle.wait(0) == 0 and handle.stdout.read() == b"abcdef"
    assert client.post(API + "/device/result", headers=headers(token), json=wire).status_code == 410
    assert client.post(API + "/device/chunk", headers=headers(token), json=chunk).status_code == 410
    assert reg.recent(1)[0].state is RequestState.FINISHED
    cancelled = relay.submit(request(device, n=2))
    cancelled.kill()
    late = sign(key, "result", device.id, result_body() | {"id": cancelled.req.id})
    assert client.post(API + "/device/result", headers=headers(token), json=late).status_code == 410
    assert reg.recent(1)[0].state is RequestState.CANCELLED


def test_other_device_cannot_upload(routes, tmp_path):
    client, reg, relay, _, _ = routes
    first, _, _ = paired(reg, tmp_path, now=int(time.time()))
    other, token, key = paired(reg, tmp_path, "other", now=int(time.time()))
    handle = relay.submit(request(first))
    part = sign(key, "chunk", other.id, dict(id=handle.req.id, seq=0, data="eA=="))
    done = sign(key, "result", other.id, result_body() | {"id": handle.req.id})
    assert client.post(API + "/device/chunk", headers=headers(token), json=part).status_code == 410
    assert client.post(API + "/device/result", headers=headers(token), json=done).status_code == 410
    assert handle.req.id in relay.handles and relay.tail(handle.req.id) == b""
    handle.kill()
    assert handle.wait(0) == 130


def test_desktop_routes_and_device_scope(routes, tmp_path):
    client, reg, relay, _, gate = routes
    device, token, _ = paired(reg, tmp_path, now=int(time.time()))
    assert client.get(API + "/devices").status_code == (401 if gate else 200)
    assert client.get(API + "/devices", headers=headers(token)).status_code == (401 if gate else 200)
    desktop = headers(DESKTOP_TOKEN)
    devices = client.get(API + "/devices", headers=desktop).json()
    assert devices == [dict(id=device.id, name=device.name, online=False, os=device.os,
                            home=device.home, last_seen=None)]
    path = API + "/sessions/telegram:42/target"
    assert client.get(path, headers=desktop).json() == {"target": "server"}
    assert client.put(path, headers=desktop, json={"target": device.name}).json() == {"target": device.name}
    assert reg.target_device_id("telegram:42") == device.id
    assert client.get(path, headers=desktop).json() == {"target": device.name}
    assert client.put(path, headers=desktop, json={"target": "missing"}).status_code == 404
    assert client.put(path, headers=desktop, json={"target": 1}).status_code == 400
    assert client.put(path, headers=desktop, json={"target": "server"}).json() == {"target": "server"}
    assert client.get(path, headers=desktop).json() == {"target": "server"}
    relay.touch(device.id)
    handle = relay.submit(request(device, session="telegram:42"))
    relay.next(device.id, 0)
    assert relay.feed(handle.req.id, 0, b"live tail")
    rows = client.get(API + "/requests?session_key=telegram:42", headers=desktop).json()
    assert rows[0]["id"] == handle.req.id and rows[0]["tail"] == "live tail" and rows[0]["state"] == "running"
    assert client.get(API + "/requests?session_key=other", headers=desktop).json() == []
    seen = client.get(API + "/devices", headers=desktop).json()[0]
    assert seen["online"] and abs(seen["last_seen"] - time.time()) < 2
    assert client.put(path, headers=desktop, json={"target": device.name}).status_code == 200
    code = client.post(API + "/pairing", headers=desktop, json={"name": "new"}).json()["code"]
    assert isinstance(reg.credential_for(code, int(time.time())), Pending)
    assert client.post(API + "/pairing", headers=desktop, json={"name": "../bad"}).status_code == 400
    assert client.post(API + f"/devices/{device.name}/revoke", headers=desktop).status_code == 200
    assert handle.wait(0) == 130 and handle.stdout.read() == b"live tail"
    assert reg.credential_for(token, int(time.time())) is None and not relay.is_online(device.id)
    assert client.get(path, headers=desktop).status_code == 404
    assert client.get(API + "/requests", headers=desktop).json()[0]["tail"] == ""


def test_poll_uses_stable_signed_key_and_does_not_block(routes, tmp_path):
    client, reg, relay, _, _ = routes
    device, token, key = paired(reg, tmp_path, now=int(time.time()))
    with ThreadPoolExecutor(1) as pool:
        poll = pool.submit(client.post, API + "/device/poll", headers=headers(token),
                           json=sign(key, "poll", device.id, {}))
        until(lambda: relay.is_online(device.id))
        start = time.monotonic()
        assert client.get(API + "/devices", headers=headers(DESKTOP_TOKEN)).status_code == 200
        assert time.monotonic() - start < 1
        handle = relay.submit(request(device))
        response = poll.result(timeout=2)
    env = verify(VerifyKey(SigningKey(reg.relay_seed).verify_key.encode()), response.json(), int(time.time()))
    assert env.kind == "poll" and env.sender == "relay"
    assert env.body["exec"]["id"] == handle.req.id and env.body["cancel"] == []
    handle.kill()


def test_pairing_transaction_binds_the_authenticated_code(tmp_path):
    with mounted(tmp_path) as (_, reg, _, _):
        now, key = int(time.time()), SigningKey.generate()
        old = reg.mint("device", now)
        assert isinstance(reg.credential_for(old, now), Pending)
        new = reg.mint("device", now)
        parsed = parse_hello(hello(key, tmp_path))
        with pytest.raises(ValueError, match="expired or already used"):
            reg.complete_pairing("device", parsed, now, code=old)
        assert isinstance(reg.credential_for(new, now), Pending)
        device, token = reg.complete_pairing("device", parsed, now, code=new)
        assert reg.credential_for(token, now) == device
