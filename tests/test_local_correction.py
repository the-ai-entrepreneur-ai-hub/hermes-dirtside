"""Fixed IPC paths, mapped peers and bounded actionable owner failures."""
import asyncio
import struct
import threading
from dataclasses import asdict

import httpx
import pytest
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth import token_auth
from network_support import mounted

from dirtside.client import Client, OWNER_MISSING
from dirtside.model import CHUNK_BYTES
from dirtside.environment import EnvironmentConnectionError
from dirtside.local import PREFIX
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_owner_correction import recorded
from test_registry import paired, request
from test_routes import headers


@pytest.mark.parametrize("peer", ["127.0.0.2", "::1", "::ffff:127.0.0.1"])
@pytest.mark.parametrize("gate", [False, True])
def test_all_loopback_forms_can_authenticate(tmp_path, peer, gate):
    with mounted(tmp_path, gate=gate) as (app, registry, *_):
        with TestClient(app, client=(peer, 12)) as client:
            assert client.get(PREFIX + "/devices", headers=headers(registry.local_secret)).status_code == 200


@pytest.mark.parametrize("status", [401, 404, 409, 413, 500, 503])
@pytest.mark.parametrize("body", [{"detail": "unavailable\n\x1b" + "x" * 400}, ["bad"], "<html>error</html>"])
def test_http_status_is_not_an_absent_owner(tmp_path, status, body):
    registry = Registry(tmp_path / "data.db")
    recorded(registry)
    client = Client(Relay(registry))
    client.http.close()
    def respond(req):
        return httpx.Response(status, **({"text": body} if isinstance(body, str) else {"json": body}))
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(EnvironmentConnectionError) as error:
            client.request("GET", "/devices")
        phrase = "unavailable" + "x" * 189 if isinstance(body, dict) else httpx.codes.get_reason_phrase(status)
        assert str(error.value) == f"Dirtside owner answered {status}: {phrase[:200]}"
        assert all(c.isprintable() for c in str(error.value))
    finally:
        client.http.close()


def test_fixed_query_paths_do_not_grow_token_exemptions(tmp_path):
    with mounted(tmp_path) as (app, registry, relay, _):
        device, _, _ = paired(registry, tmp_path)
        relay.touch(device.id)
        with TestClient(app, client=("127.0.0.1", 12)) as client:
            auth = headers(registry.local_secret)
            before = set(token_auth._token_routes)
            for n in range(10):
                req = request(device, n=n + 1)
                assert client.post(PREFIX + "/exec", headers=auth, json=asdict(req)).status_code == 200
                assert client.post(PREFIX + "/kill", params={"id": req.id}, headers=auth, json={}).json() == {
                    "cancelled": True}
                assert client.get(PREFIX + "/stream", params={"id": req.id}, headers=auth).status_code == 200
            assert token_auth._token_routes == before
            for id in ("../bad", "r_" + "a" * 25, "", "r_" + "A" * 24):
                assert client.get(PREFIX + "/stream", params={"id": id}, headers=auth).status_code == 400
                assert client.post(PREFIX + "/kill", params={"id": id}, headers=auth, json={}).status_code == 400
            assert not relay.handles and not relay._streams


def test_stream_poll_and_disconnect_close_run_off_event_loop(tmp_path, monkeypatch):
    with mounted(tmp_path) as (_, registry, relay, module):
        device, _, _ = paired(registry, tmp_path)
        relay.touch(device.id)
        handle = relay.submit(request(device))
        assert relay.feed(handle.req.id, 0, b"x")
        threads = []
        poll, close = handle.poll, relay.close
        def observed_poll():
            threads.append(("poll", threading.get_ident()))
            return poll()
        def observed_close(*args):
            threads.append(("close", threading.get_ident()))
            return close(*args)
        monkeypatch.setattr(handle, "poll", observed_poll)
        monkeypatch.setattr(relay, "close", observed_close)
        async def consume():
            event_loop = threading.get_ident()
            stream = module.auth.local.output(handle)
            assert await anext(stream) == b"\0\0\0\1"
            await stream.aclose()
            return event_loop
        event_loop = asyncio.run(consume())
        assert {kind for kind, _ in threads} == {"poll", "close"}
        assert all(tid != event_loop for _, tid in threads)
        assert handle.stdout.closed and registry.recent(1)[0].state.value == "lost"


@pytest.mark.parametrize("failure", ["malformed", "status", "read"])
def test_stream_failures_preserve_partial_output_and_exact_reason(tmp_path, failure):
    registry = Registry(tmp_path / "data.db")
    device, _, _ = paired(registry, tmp_path)
    recorded(registry)
    client = Client(Relay(registry))
    client.http.close()
    def respond(req):
        if req.url.path.endswith("/exec"):
            return httpx.Response(200, json={"state": "queued"})
        if failure == "read":
            raise httpx.ReadError("broken pipe")
        if failure == "status":
            return httpx.Response(503, json={"detail": "temporarily unavailable"})
        return httpx.Response(200, content=struct.pack("!I", 4) + b"keep" + struct.pack("!I", CHUNK_BYTES + 1))
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        handle = client.submit(request(device))
        assert handle.wait(3) == 124
        assert handle.stdout.read() == (b"keep" if failure == "malformed" else b"")
        expected = "Dirtside owner answered 503: temporarily unavailable" if failure == "status" else OWNER_MISSING
        assert handle.outcome.reason == expected and handle.state.value == "lost"
        handle.stdout.close()
    finally:
        client.http.close()


def test_reused_pid_does_not_receive_the_local_secret(tmp_path):
    registry = Registry(tmp_path / "data.db")
    recorded(registry, started=1)
    client = Client(Relay(registry))
    client.http.close()
    calls = []
    client.http = httpx.Client(transport=httpx.MockTransport(lambda req: calls.append(req)))
    try:
        assert not client.is_online("unused")
        with pytest.raises(EnvironmentConnectionError, match=OWNER_MISSING):
            client.request("GET", "/devices")
        assert not calls
    finally:
        client.http.close()


def test_submit_does_not_switch_from_absent_to_a_new_owner(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "data.db")
    device, _, _ = paired(registry, tmp_path)
    client = Client(Relay(registry))
    client.http.close()
    calls = []
    def respond(req):
        calls.append(req)
        return httpx.Response(200, json={"state": "queued"})
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    origins = iter([None, "http://127.0.0.1:1234/local", "http://127.0.0.1:1234/local"])
    monkeypatch.setattr(client, "origin", lambda: next(origins))
    handle = None
    try:
        try:
            handle = client.submit(request(device))
        except EnvironmentConnectionError as exc:
            assert str(exc) == OWNER_MISSING
        else:
            pytest.fail("submission must stop at its absent discovery result")
        assert calls == []
    finally:
        if handle is not None:
            assert handle.wait(3) == 124
            handle.stdout.close()
        client.http.close()
