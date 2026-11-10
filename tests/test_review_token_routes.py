"""Real scoped registration and handler-owned refusal, including stale outer routes."""
import base64
import os
import time

import pytest
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth import token_auth
from hermes_constants import hermes_home_key
from nacl.signing import SigningKey
from route_support import MissingMethodContext, plugin_context, record_routes, register

import dirtside
from dirtside.auth import DEVICE_PATHS, LOCAL_PATHS, register_device_routes
from network_support import DESKTOP_TOKEN, mounted
from test_registry import paired

PATHS = DEVICE_PATHS + LOCAL_PATHS


def forbidden(*args, **kwargs):
    raise AssertionError("private token registration was called")


def stale_outer_routes():
    for path in PATHS:
        token_auth.register_token_route(path)


def credentials(provider, root):
    device, token, _ = paired(provider.registry, root, now=int(time.time()))
    provider.relay._owner_pid = os.getpid()
    code = provider.registry.mint("pending", int(time.time()))
    return {"device": token, "pair": code, "local": provider.registry.local_secret,
            "dashboard": DESKTOP_TOKEN}, device


def endpoints():
    return [(path, "POST", "pair" if path.endswith("/pair") else "device") for path in DEVICE_PATHS] + [
        (path, "POST" if path.endswith(("/exec", "/kill")) else "GET", "local") for path in LOCAL_PATHS
    ] + [(LOCAL_PATHS[3], "POST", "local")]


def request(web, method, path, token):
    return web.request(method, path, headers={"Authorization": "Bearer " + token},
                       params={"id": "r_" + "0" * 24}, json={})


def closed_responses(provider, root, gate):
    creds, _ = credentials(provider, root)
    with mounted(root, gate=gate, relay=provider.relay, provider=provider) as (app, *_):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            return [(path, method, request(web, method, path, creds[kind]).status_code)
                    for path, method, kind in endpoints()]


def working_local(provider, root):
    with mounted(root, relay=provider.relay, provider=provider) as (app, *_):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            response = request(web, "GET", LOCAL_PATHS[3], provider.registry.local_secret)
            assert response.status_code == 200, response.text


def warning(caplog, cause):
    lines = [record.getMessage() for record in caplog.records if record.name == "dirtside.auth"]
    assert len(lines) == 1 and len(lines[0]) < 160
    assert "disabled" in lines[0] and cause in lines[0] and "registration detail" not in lines[0]


def test_public_token_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(token_auth, "register_token_route", forbidden)
    with plugin_context() as ctx:
        observed = record_routes(ctx, monkeypatch)
        provider = register(ctx, tmp_path, monkeypatch)
        expected = [(path, "dirtside", ("dirtside",)) for path in DEVICE_PATHS] + [
            (path, "dirtside", ("dirtside-local",)) for path in LOCAL_PATHS]
        assert observed.calls == expected and provider.routes.enabled
        for handle, (path, _, scopes) in zip(observed.handles, expected):
            assert handle.kind == "dashboard_token_route" and handle.key == path and handle.active
            assert handle.value.registration.value is provider
            assert handle.value.required_scopes == frozenset(scopes)
            assert handle.value.home == hermes_home_key()
            assert token_auth.is_token_route(path)
        ctx._manager.unload(ctx.manifest)
        ctx._manager.unload(ctx.manifest)
        assert not provider.routes.enabled and all(not h.active for h in observed.handles)
        assert all(not token_auth.is_token_route(path) for path in PATHS)


def test_disposal_failure_still_closes_routes(tmp_path, monkeypatch):
    with plugin_context() as ctx:
        observed = record_routes(ctx, monkeypatch)
        provider = register(ctx, tmp_path, monkeypatch)
        handle, attempts = observed.handles[4], []
        real = handle.dispose
        def broken():
            attempts.append(True)
            real()
            raise RuntimeError("outer registration disposal failed")
        monkeypatch.setattr(handle, "dispose", broken)
        provider.routes.dispose()
        provider.routes.dispose()
        assert not provider.routes.enabled and all(not h.active for h in observed.handles)
        assert attempts == [True] and not provider.routes.registrations
        assert all(not token_auth.is_token_route(path) for path in PATHS)


def test_auth_registration_refusal_never_registers_routes(tmp_path, monkeypatch):
    with plugin_context() as ctx:
        working_local(register(ctx, tmp_path, monkeypatch), tmp_path)
        ctx._manager.unload()
        observed, offered = record_routes(ctx, monkeypatch), []
        monkeypatch.setattr(ctx, "register_dashboard_auth_provider", lambda value: offered.append(value))
        dirtside.register(ctx)
        assert len(offered) == 1 and not offered[0].routes.enabled and observed.calls == []


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("refusal", ["raise", "none"])
@pytest.mark.parametrize("position", [1, 5, 9])
def test_token_registration_refusal(tmp_path, monkeypatch, caplog, gate, refusal, position):
    with plugin_context() as ctx:
        working_local(register(ctx, tmp_path, monkeypatch), tmp_path)
        ctx._manager.unload()
        stale_outer_routes()
        monkeypatch.setattr(token_auth, "register_token_route", forbidden)
        observed = record_routes(ctx, monkeypatch, position, refusal)
        provider = register(ctx, tmp_path, monkeypatch)
        assert not provider.routes.enabled and not provider.relay.handles
        assert len(observed.handles) == position - 1 and all(not h.active for h in observed.handles)
        assert not provider.routes.registrations
        assert len(observed.calls) == position
        responses = closed_responses(provider, tmp_path, gate)
        assert all(status == 401 for _, _, status in responses), responses
        warning(caplog, "refused" if refusal == "none" else "failed")


@pytest.mark.parametrize("gate", [False, True])
def test_cross_credentials(tmp_path, monkeypatch, gate):
    with plugin_context() as ctx:
        stale_outer_routes()
        provider = register(ctx, tmp_path, monkeypatch)
        creds, _ = credentials(provider, tmp_path)
        with mounted(tmp_path, gate=gate, relay=provider.relay, provider=provider) as (app, _, _, module):
            with TestClient(app, client=("127.0.0.1", 10)) as web:
                assert request(web, "GET", LOCAL_PATHS[3], creds["local"]).status_code == 200
                key = SigningKey.generate()
                hello = dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name="pending",
                             os="test-os", arch="", home=str(tmp_path), temp_dir=str(tmp_path), agent_version="0.1.0")
                reply = web.post(DEVICE_PATHS[0], headers={"Authorization": "Bearer " + creds["pair"]},
                                 json=module.wire.sign(key, "hello", "pending", hello))
                assert reply.status_code == 200
                for path, method, kind in endpoints():
                    wrong = "local" if kind != "local" else "device"
                    response = request(web, method, path, creds[wrong])
                    assert response.status_code == 403, (path, response.text)
                    assert response.json() == {"error": "insufficient_scope", "detail": "Forbidden"}
                    assert request(web, method, path, creds["dashboard"]).status_code == 401


@pytest.mark.parametrize("gate", [False, True])
def test_unload_closes_handlers(tmp_path, monkeypatch, gate):
    with plugin_context() as ctx:
        stale_outer_routes()
        provider = register(ctx, tmp_path, monkeypatch)
        creds, _ = credentials(provider, tmp_path)
        with mounted(tmp_path, gate=gate, relay=provider.relay, provider=provider) as (app, *_):
            with TestClient(app, client=("127.0.0.1", 10)) as web:
                assert request(web, "GET", LOCAL_PATHS[3], creds["local"]).status_code == 200
                ctx._manager.unload(ctx.manifest)
                responses = [(path, request(web, method, path, creds[kind]).status_code)
                             for path, method, kind in endpoints()]
                assert all(status == 401 for _, status in responses), responses


def test_registration_is_instance_owned(tmp_path, monkeypatch):
    with plugin_context() as ctx:
        good = register(ctx, tmp_path, monkeypatch)
        bad = register_device_routes(MissingMethodContext(ctx))
        assert good.routes.enabled and not bad.enabled
        working_local(good, tmp_path)
