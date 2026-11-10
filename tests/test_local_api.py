"""Local IPC stays private, bounded and byte-exact with either dashboard gate."""
import json
import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth.token_auth import is_token_route
from network_support import listening, mounted, until
from dirtside.client import Client, OWNER_MISSING, frames
from dirtside.environment import EnvironmentConnectionError
from dirtside.local import BODY_BYTES, PREFIX
from dirtside.model import CHUNK_BYTES, Outcome, RequestState
from dirtside.protocol import sign
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired, request
from test_routes import headers
from test_owner_correction import recorded

@pytest.fixture(params=[False, True], ids=["gate-off", "gate-on"])
def local_api(tmp_path, request):
    with mounted(tmp_path, gate=request.param) as (app, registry, relay, module):
        with TestClient(app, base_url="http://127.0.0.1:8123", client=("127.0.0.1", 1234)) as client:
            yield client, registry, relay, module

def test_private_files_are_stable_and_concurrent(tmp_path):
    path = tmp_path / "data.db"
    with ThreadPoolExecutor(8) as pool:
        registries = list(pool.map(lambda _: Registry(path), range(16)))
    assert len({r.local_secret for r in registries}) == 1
    assert len(bytes.fromhex(registries[0].local_secret)) == 32
    assert len({r.relay_seed for r in registries}) == 1
    for name in ("local.secret", "relay.key"):
        assert path.with_name(name).stat().st_mode & 0o777 == 0o600
    secret = path.with_name("local.secret")
    secret.chmod(0o644)
    Registry(path)
    assert secret.stat().st_mode & 0o777 == 0o600

def test_owner_uses_server_not_forwarded_host_and_rewrites_port(local_api, monkeypatch):
    client, registry, relay, module = local_api
    path = registry.path.with_name("owner.json")
    assert not path.exists()
    assert relay._owner_pid is None
    before = time.time()
    response = client.get(PREFIX + "/devices", headers=headers(registry.local_secret) | {
        "Host": "external.invalid", "X-Forwarded-Host": "other.invalid"})
    assert response.status_code == 200
    assert not path.exists() and relay._owner_pid is None
    rejected = client.post("/api/plugins/dirtside/device/poll", headers=headers(registry.local_secret))
    assert rejected.status_code == 403
    assert rejected.json() == {"error": "insufficient_scope", "detail": "Forbidden"}
    assert not path.exists() and relay._owner_pid is None
    device, token, key = paired(registry, registry.path.parent)
    body = dict(id="r_" + "a" * 24, seq=0, data="")
    assert client.post("/api/plugins/dirtside/device/chunk", headers=headers(token) | {
        "Host": "external.invalid", "X-Forwarded-Host": "other.invalid"},
        json=sign(key, "chunk", device.id, body)).status_code == 410
    record = json.loads(path.read_text())
    assert record == dict(origin="http://127.0.0.1:8123", pid=os.getpid(), started=module.auth.process_started(os.getpid()))
    assert record["started"] <= before <= time.time()
    assert path.stat().st_mode & 0o777 == 0o600
    changed = path.stat().st_mtime_ns
    client.get(PREFIX + "/devices", headers=headers(registry.local_secret))
    assert path.stat().st_mtime_ns == changed
    module.record_owner(SimpleNamespace(scope={"server": ("0.0.0.0", 9123)}))
    assert json.loads(path.read_text())["origin"] == "http://127.0.0.1:9123"
    module.record_owner(SimpleNamespace(scope={"server": ("::1", 8124)}))
    assert json.loads(path.read_text())["origin"] == "http://[::1]:8124"
    changed_pid = os.getpid() + 1
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: changed_pid)
        patch.setattr(module.auth, "process_started", lambda _: record["started"])
        module.record_owner(SimpleNamespace(scope={"server": ("::1", 8124)}))
    assert json.loads(path.read_text())["pid"] == changed_pid

def test_local_secret_is_not_a_device_credential(local_api, tmp_path):
    client, registry, relay, _ = local_api
    device, token, key = paired(registry, tmp_path)
    for value in ("", "wrong"):
        assert client.get(PREFIX + "/devices", headers=headers(value)).status_code == 401
    for response in (client.get(PREFIX + "/devices", headers=headers(token)),
                     client.post("/api/plugins/dirtside/device/poll", headers=headers(registry.local_secret),
                                 content=b"{")):
        assert response.status_code == 403
        assert response.json() == {"error": "insufficient_scope", "detail": "Forbidden"}
    assert not relay.is_online(device.id)
    assert client.get(PREFIX + "/devices", headers=headers(registry.local_secret)).status_code == 200
    relay.cancels[device.id].add("r_" + "ab" * 12)
    assert client.post("/api/plugins/dirtside/device/poll", headers=headers(token),
                       json=sign(key, "poll", device.id, {"running": []})).status_code == 200

@pytest.mark.parametrize("peer", ["10.0.0.1", "::ffff:10.0.0.1", "testclient"])
def test_non_loopback_cannot_use_a_valid_secret(local_api, peer):
    client, registry, _, _ = local_api
    with TestClient(client.app, client=(peer, 1234)) as external:
        assert external.get(PREFIX + "/devices", headers=headers(registry.local_secret)).status_code == 403

@pytest.mark.parametrize("change", [
    {"id": "invalid"}, {"id": 123}, {"device_id": "../bad"}, {"session_key": None},
    {"task_id": 1}, {"timeout_s": True}, {"stdin": 1}, {"cwd": "relative"}, {"script": "bad\0"},
    {"extra": 1}, {"device_id": "f" * 32},
])
def test_invalid_execution_never_dispatches(local_api, tmp_path, change):
    client, registry, relay, _ = local_api
    device, _, _ = paired(registry, tmp_path)
    relay.touch(device.id)
    response = client.post(PREFIX + "/exec", headers=headers(registry.local_secret),
                           json=asdict(request(device)) | change)
    assert response.status_code in (400, 409)
    assert registry.recent(10) == [] and not relay.handles

def test_body_bound_counts_bytes_without_content_length(local_api):
    client, registry, relay, _ = local_api
    response = client.post(PREFIX + "/exec", headers=headers(registry.local_secret),
                           content=iter([b" " * CHUNK_BYTES] * (BODY_BYTES // CHUNK_BYTES + 1)))
    assert response.status_code == 413 and not relay.handles

def test_finished_before_stream_and_exact_paths(local_api, tmp_path):
    client, registry, relay, _ = local_api
    device, _, _ = paired(registry, tmp_path)
    relay.touch(device.id)
    req = request(device)
    auth = headers(registry.local_secret)
    assert client.post(PREFIX + "/exec", headers=auth, json=asdict(req)).status_code == 200
    assert client.post(PREFIX + "/exec", headers=auth, json=asdict(req)).status_code == 409
    stream, kill = PREFIX + f"/stream?id={req.id}", PREFIX + f"/kill?id={req.id}"
    assert is_token_route(PREFIX + "/stream") and is_token_route(PREFIX + "/kill")
    assert not is_token_route(PREFIX + "/other")
    assert not is_token_route(PREFIX + f"/requests/{req.id}/stream")
    data = b"\0\xff\n" + b'{"state":"finished","exit_code":99}\n'
    assert relay.feed(req.id, 0, data)
    assert relay.close(req.id, Outcome(RequestState.FINISHED, 3, 2, False, "reason"))
    response = client.get(stream, headers=auth)
    parsed = list(frames(response))
    assert b"".join(parsed[:-1]) == data
    assert parsed[-1] == Outcome(RequestState.FINISHED, 3, 2, False, "reason")
    assert client.get(stream, headers=auth).status_code == 410
    assert client.post(kill, headers=auth, json={}).status_code == 200
    assert not relay._streams

def test_unattached_stream_is_abandoned(local_api, tmp_path):
    client, registry, relay, _ = local_api
    device, _, _ = paired(registry, tmp_path)
    relay.touch(device.id)
    req = request(device)
    assert client.post(PREFIX + "/exec", headers=headers(registry.local_secret), json=asdict(req)).status_code == 200
    handle = relay._streams[req.id][0]
    relay.abandon(req.id)
    assert handle.stdout.closed and handle.wait(0) == 255
    assert registry.recent(1)[0].reason == "gateway stopped reading output"
    assert not relay._streams

@pytest.mark.parametrize("record", [{}, {"pid": -1, "origin": "http://127.0.0.1:1"},
    {"pid": os.getpid(), "origin": "http://127.0.0.1:1"},
    {"pid": os.getpid(), "origin": "http://outside.invalid:80"},
    {"pid": os.getpid(), "origin": "http://127.0.0.1:80@outside.invalid:80"}])
def test_missing_or_unsafe_owner_fails_closed(tmp_path, record):
    registry = Registry(tmp_path / "data.db")
    recorded(registry)
    data = json.loads(registry.path.with_name("owner.json").read_text())
    registry.path.with_name("owner.json").write_text(json.dumps({"started": data["started"]} | record))
    client = Client(Relay(registry))
    try:
        with pytest.raises(EnvironmentConnectionError, match=OWNER_MISSING):
            client.is_online("device")
    finally:
        client.http.close()

def test_disconnect_closes_request_without_device_output(tmp_path):
    with mounted(tmp_path) as (app, registry, relay, _), listening(app) as url:
        device, _, _ = paired(registry, tmp_path)
        relay.touch(device.id)
        req = replace(request(device), command="silent", script="silent")
        with httpx.Client(base_url=url, headers=headers(registry.local_secret), trust_env=False) as client:
            assert client.post(PREFIX + "/exec", json=asdict(req)).status_code == 200
            handle = relay.handles[req.id]
            with client.stream("GET", PREFIX + "/stream", params={"id": req.id}) as response:
                assert response.status_code == 200
            until(lambda: handle.poll() == 255)
        assert handle.stdout.closed
        assert registry.recent(1)[0].reason == "gateway stopped reading output"

def test_frame_limit_and_split_headers():
    data = b"a" * CHUNK_BYTES + b"\xff"
    outcome = dict(state="finished", exit_code=0, duration_ms=0, truncated=False, reason="")
    wire = struct.pack("!I", CHUNK_BYTES) + data[:-1] + struct.pack("!I", 1) + data[-1:] + b"\0" * 4
    wire += json.dumps(outcome).encode() + b"\n"
    class Response:
        def iter_bytes(self):
            return (wire[n:n + 3] for n in range(0, len(wire), 3))
    parts = list(frames(Response()))
    assert b"".join(parts[:-1]) == data and parts[-1].exit_code == 0
