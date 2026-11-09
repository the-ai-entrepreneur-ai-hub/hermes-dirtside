"""Scoped registration and handler-owned refusal, including stale outer routes."""
import base64
import os
import time

import pytest
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth import token_auth
from nacl.signing import SigningKey

import dirtside
import dirtside.auth as auth_module
from dirtside.auth import DEVICE_PATHS, LOCAL_PATHS
from network_support import DESKTOP_TOKEN, mounted
from test_registry import paired

PATHS = DEVICE_PATHS + LOCAL_PATHS


class Handle:
    def __init__(self):
        self.disposed = 0

    def dispose(self):
        self.disposed += 1


class LegacyContext:
    def __init__(self):
        self.auth, self.callbacks, self.handles, self.calls = None, [], [], []

    def get_config(self, name, default=None):
        return default

    def register_dashboard_auth_provider(self, provider):
        self.auth = provider
        return Handle()

    def on_unload(self, callback):
        self.callbacks.append(callback)
        return Handle()

    def register(self, *args, **kwargs):
        return Handle()

    register_terminal_environment_provider = register
    register_middleware = register
    register_cli_command = register
    register_command = register
    register_system_prompt_section = register


class PublicContext(LegacyContext):
    def __init__(self, fail_at=None, refusal="raise"):
        super().__init__()
        self.fail_at, self.refusal = fail_at, refusal

    def register_dashboard_token_route(self, path, *, provider, required_scopes=()):
        self.calls.append((path, provider, required_scopes))
        if len(self.calls) == self.fail_at:
            if self.refusal == "none":
                return None
            raise RuntimeError("registration detail must not be logged")
        handle = Handle()
        self.handles.append(handle)
        return handle


def register(ctx, root, monkeypatch):
    monkeypatch.setattr(dirtside, "plugin_data_dir", lambda _: root)
    dirtside.register(ctx)
    return ctx.auth


def patch_legacy(monkeypatch, callback):
    monkeypatch.setattr(token_auth, "register_token_route", callback)
    monkeypatch.setattr(auth_module, "register_token_route", callback, raising=False)


def forbidden(*args, **kwargs):
    raise AssertionError("private token fallback was called")


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


def warning(caplog):
    lines = [record.getMessage() for record in caplog.records if record.name == "dirtside.auth"]
    assert len(lines) == 1 and len(lines[0]) < 160
    assert "disabled" in lines[0] and "registration detail" not in lines[0]


def test_public_token_registration(tmp_path, monkeypatch):
    patch_legacy(monkeypatch, forbidden)
    ctx = PublicContext()
    provider = register(ctx, tmp_path, monkeypatch)
    assert ctx.calls == [(path, "dirtside", ("dirtside",)) for path in DEVICE_PATHS] + [
        (path, "dirtside", ("dirtside-local",)) for path in LOCAL_PATHS]
    assert provider.routes.enabled and len(ctx.callbacks) == 1
    ctx.callbacks[0]()
    ctx.callbacks[0]()
    assert not provider.routes.enabled and all(h.disposed == 1 for h in ctx.handles)


def test_disposal_failure_still_closes_routes(tmp_path, monkeypatch):
    ctx = PublicContext()
    provider = register(ctx, tmp_path, monkeypatch)
    handle = ctx.handles[4]
    def broken():
        handle.disposed += 1
        raise RuntimeError("outer registration disposal failed")
    handle.dispose = broken
    ctx.callbacks[0]()
    ctx.callbacks[0]()
    assert not provider.routes.enabled and all(h.disposed == 1 for h in ctx.handles)


def test_auth_registration_refusal_never_registers_routes(tmp_path, monkeypatch):
    ctx = PublicContext()
    ctx.register_dashboard_auth_provider = lambda value: setattr(ctx, "auth", value)
    provider = register(ctx, tmp_path, monkeypatch)
    assert not provider.routes.enabled and ctx.calls == []


def test_legacy_token_registration(tmp_path, monkeypatch):
    seen, real = [], token_auth.register_token_route
    def record(path):
        seen.append(path)
        return real(path)
    patch_legacy(monkeypatch, record)
    ctx = LegacyContext()
    register(ctx, tmp_path, monkeypatch)
    assert seen == list(PATHS)
    assert all(token_auth.is_token_route(path) for path in PATHS)


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("refusal", ["raise", "none"])
@pytest.mark.parametrize("position", [1, 5, 9])
def test_token_registration_refusal(tmp_path, monkeypatch, caplog, gate, refusal, position):
    stale_outer_routes()
    legacy, real = [], token_auth.register_token_route
    def fallback(path):
        legacy.append(path)
        return real(path)
    patch_legacy(monkeypatch, fallback)
    ctx = PublicContext(position, refusal)
    provider = register(ctx, tmp_path, monkeypatch)
    responses = closed_responses(provider, tmp_path, gate)
    assert all(status in {401, 404} for _, _, status in responses), responses
    assert not provider.routes.enabled
    assert len(ctx.handles) == position - 1 and all(h.disposed == 1 for h in ctx.handles)
    assert len(ctx.calls) == position and not provider.relay.handles
    assert legacy == []
    warning(caplog)


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("public", [False, True])
def test_cross_credentials(tmp_path, monkeypatch, gate, public):
    stale_outer_routes()
    ctx = PublicContext() if public else LegacyContext()
    provider = register(ctx, tmp_path, monkeypatch)
    creds, _ = credentials(provider, tmp_path)
    with mounted(tmp_path, gate=gate, relay=provider.relay, provider=provider) as (app, _, _, module):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            assert request(web, "GET", LOCAL_PATHS[3], creds["local"]).status_code == 200
            for path, method, kind in endpoints():
                wrong = ("local", "dashboard") if kind != "local" else ("device", "dashboard")
                for name in wrong:
                    assert request(web, method, path, creds[name]).status_code == 401
            key = SigningKey.generate()
            hello = dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name="pending",
                         os="test-os", arch="", home=str(tmp_path), temp_dir=str(tmp_path), agent_version="0.1.0")
            reply = web.post(DEVICE_PATHS[0], headers={"Authorization": "Bearer " + creds["pair"]},
                             json=module.wire.sign(key, "hello", "pending", hello))
            assert reply.status_code == 200


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("public", [False, True])
def test_unload_closes_handlers(tmp_path, monkeypatch, gate, public):
    stale_outer_routes()
    ctx = PublicContext() if public else LegacyContext()
    provider = register(ctx, tmp_path, monkeypatch)
    creds, _ = credentials(provider, tmp_path)
    with mounted(tmp_path, gate=gate, relay=provider.relay, provider=provider) as (app, *_):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            assert request(web, "GET", LOCAL_PATHS[3], creds["local"]).status_code == 200
            for callback in reversed(ctx.callbacks):
                callback()
            responses = [(path, request(web, method, path, creds[kind]).status_code)
                         for path, method, kind in endpoints()]
            assert all(status in {401, 404} for _, status in responses), responses


def test_registration_is_instance_owned(tmp_path, monkeypatch):
    good = register(PublicContext(), tmp_path, monkeypatch)
    bad = register(PublicContext(3, "none"), tmp_path, monkeypatch)
    assert good.routes.enabled and not bad.routes.enabled


def test_present_noncallable_seam_is_not_legacy(tmp_path, monkeypatch, caplog):
    patch_legacy(monkeypatch, forbidden)
    ctx = LegacyContext()
    ctx.register_dashboard_token_route = None
    provider = register(ctx, tmp_path, monkeypatch)
    assert not provider.routes.enabled
    warning(caplog)


def test_legacy_registration_failure(tmp_path, monkeypatch, caplog):
    seen, real = [], token_auth.register_token_route
    def record(path):
        seen.append(path)
        if len(seen) == 3:
            raise RuntimeError("registration detail must not be logged")
        return real(path)
    patch_legacy(monkeypatch, record)
    provider = register(LegacyContext(), tmp_path, monkeypatch)
    assert seen == list(PATHS[:3]) and not provider.routes.enabled
    warning(caplog)
