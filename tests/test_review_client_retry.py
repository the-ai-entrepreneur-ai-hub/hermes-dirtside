"""Only a pre-handler disabled-route 401 may be replayed, with the same request."""
import json
import struct
import time
from collections import Counter
from contextlib import contextmanager

import httpx
import pytest
from client_support import client_relay
from network_support import until

from dirtside.client import Client
from dirtside.environment import EnvironmentConnectionError
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_environment import device_setup
from test_owner_correction import recorded
from test_registry import paired, request

DISABLED = "Dirtside token routes are disabled"


@contextmanager
def client_for(tmp_path, respond):
    reg = Registry(tmp_path / "data.db")
    device, *_ = paired(reg, tmp_path)
    recorded(reg)
    client = Client(Relay(reg))
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        yield client, request(device)
    finally:
        client.http.close()


def complete():
    return httpx.Response(200, content=struct.pack("!I", 4) + b"done" + b"\0" * 4 + json.dumps(dict(
        state="finished", exit_code=0, duration_ms=1, truncated=False, reason="")).encode())


@pytest.mark.parametrize("stage", ["exec", "stream"])
def test_exact_disabled_route_retries_preserve_request(tmp_path, stage):
    calls, rejected = [], []
    def respond(req):
        route = req.url.path.rsplit("/", 1)[1]
        calls.append((route, req.content if route == "exec" else req.url.params["id"]))
        if route == stage and sum(name == stage for name, _ in calls) <= 3:
            response = httpx.Response(401, json={"detail": DISABLED})
            rejected.append(response)
            return response
        return httpx.Response(200, json={"state": "queued"}) if route == "exec" else complete()
    with client_for(tmp_path, respond) as (client, req):
        handle = client.submit(req)
        try:
            assert handle.wait(5) == 0, handle.outcome
            assert handle.stdout.read() == b"done"
            assert Counter(name for name, _ in calls) == {"exec": 4 if stage == "exec" else 1,
                                                         "stream": 4 if stage == "stream" else 1}
            assert {json.loads(value)["id"] for name, value in calls if name == "exec"} == {req.id}
            assert {value for name, value in calls if name == "stream"} == {req.id}
            assert all(response.is_closed for response in rejected)
            assert not client.handles
        finally:
            handle.stdout.close()


@pytest.mark.parametrize("stage", ["exec", "stream"])
@pytest.mark.parametrize("status,body", [
    (401, {"detail": DISABLED + "."}),
    (401, {"detail": DISABLED + "\n"}),
    (401, {"detail": "invalid local credential"}),
    (401, [DISABLED]),
    (401, "not json"),
    (403, {"detail": DISABLED}),
    (409, {"detail": DISABLED}),
    (410, {"detail": DISABLED}),
    (503, {"detail": DISABLED}),
])
def test_other_rejections_are_never_retried(tmp_path, stage, status, body):
    calls = Counter()
    def respond(req):
        route = req.url.path.rsplit("/", 1)[1]
        calls[route] += 1
        if route == stage:
            return httpx.Response(status, **({"text": body} if isinstance(body, str) else {"json": body}))
        return httpx.Response(200, json={"state": "queued"})
    with client_for(tmp_path, respond) as (client, req):
        if stage == "exec":
            with pytest.raises(EnvironmentConnectionError, match=f"answered {status}"):
                client.submit(req)
        else:
            handle = client.submit(req)
            try:
                assert handle.wait(3) == 255
                assert f"answered {status}" in handle.outcome.reason
            finally:
                handle.stdout.close()
        assert calls[stage] == 1


@pytest.mark.parametrize("stage", ["exec", "stream"])
def test_disabled_route_retry_has_one_fixed_short_deadline(tmp_path, stage):
    calls, responses = Counter(), []
    def respond(req):
        route = req.url.path.rsplit("/", 1)[1]
        calls[route] += 1
        response = (httpx.Response(401, json={"detail": DISABLED}) if route == stage else
                    httpx.Response(200, json={"state": "queued"}))
        responses.append(response)
        return response
    with client_for(tmp_path, respond) as (client, req):
        started = time.monotonic()
        if stage == "exec":
            with pytest.raises(EnvironmentConnectionError, match=DISABLED):
                client.submit(req)
        else:
            handle = client.submit(req)
            try:
                assert handle.wait(5) == 255
                assert DISABLED in handle.outcome.reason
            finally:
                handle.stdout.close()
        assert 2 <= time.monotonic() - started < 4.5
        assert 2 <= calls[stage] <= 100
        assert all(response.is_closed for response in responses)


def test_disabled_response_does_not_retry_other_local_routes(tmp_path):
    calls = []
    def respond(req):
        calls.append(req)
        return httpx.Response(401, json={"detail": DISABLED})
    with client_for(tmp_path, respond) as (client, _):
        for method, path in [("GET", "/devices"), ("POST", "/devices"), ("POST", "/kill")]:
            with pytest.raises(EnvironmentConnectionError, match=DISABLED):
                client.request(method, path)
        assert len(calls) == 3


@pytest.mark.parametrize("stage", ["exec", "stream"])
def test_real_local_route_recovers_without_duplicate_execution(tmp_path, stage):
    relay, device, fake = device_setup(tmp_path)
    marker = tmp_path / "executed"
    with client_relay(relay) as worker, fake:
        client = worker.connection()
        transport = client.http._transport
        attempts, rejected = [], []
        def route(req):
            if req.url.path.endswith("/" + stage):
                attempts.append(req)
                if len(attempts) <= 3:
                    response = httpx.Response(401, json={"detail": DISABLED})
                    rejected.append(response)
                    return response
            return transport.handle_request(req)
        client.http._transport = httpx.MockTransport(route)
        req = request(device, command=f"printf x >> '{marker}'; printf done")
        handle = client.submit(req)
        try:
            assert handle.wait(6) == 0, handle.outcome
            assert handle.stdout.read() == b"done" and marker.read_text() == "x"
            until(lambda: not fake.running)
            assert len(relay.registry.recent(10)) == 1 and len(attempts) == 4
            assert all(response.is_closed for response in rejected)
        finally:
            handle.stdout.close()
            transport.close()
