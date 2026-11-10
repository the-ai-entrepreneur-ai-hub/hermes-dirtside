"""Foreign bound and legacy unbound gates use real providers and working controls."""
import pytest
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth import TokenPrincipal, get_provider, token_auth
from nacl.signing import SigningKey
from notice_support import (
    Clock, FOREIGN, FOREIGN_TOKEN, UNBOUND, UNBOUND_TOKEN, ForeignTokenProvider,
    active_poll, envelope, foreign_rejected, gateway,
)
from network_support import mounted
from route_support import MissingMethodContext, plugin_context, record_routes, register
from test_registry import paired
from test_revoke_exit import device_path, explicit
from test_revoke_notice import core_generic
from test_routes import API, headers, hello


@pytest.mark.parametrize("kind", ["device", "pair", "local", "retained"])
def test_credentials_stay_on_their_own_routes(tmp_path, monkeypatch, kind):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, _):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            device, token, key = paired(reg, tmp_path, now=clock.now - 1)
            if kind == "pair":
                token = reg.mint("pending", clock.now)
            elif kind == "local":
                token = reg.local_secret
            elif kind == "retained":
                reg.revoke(device.name, clock.now)
            foreign_rejected(web, token)
            if kind == "pair":
                key = SigningKey.generate()
                response = web.post(device_path("hello"), headers=headers(token),
                                    json=envelope(key, "hello", "pending", hello(key, tmp_path, "pending")))
                assert response.status_code == 200, response.text
            elif kind == "local":
                assert web.get(API + "/local/devices", headers=headers(token)).status_code == 200
            elif kind == "retained":
                explicit(web.post(device_path("poll"), headers=headers(token), json=envelope(key, "poll", device.id, {})))
            else:
                active_poll(web, relay, device, token, key)


def test_foreign_provider_cannot_vouch_as_dirtside(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, _), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now)
        foreign = get_provider("notice-foreign")
        real = foreign.verify_token
        monkeypatch.setattr(foreign, "verify_token", lambda *, token:
                            TokenPrincipal("device", "dirtside", ("foreign",)) if token != FOREIGN_TOKEN else real(token=token))
        foreign_rejected(web, token)
        active_poll(web, relay, device, token, key)


def test_gateway_clock_setback_reopens_only_inside_window(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, provider):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            device, token, key = paired(reg, tmp_path, now=clock.now - 1)
            active_poll(web, relay, device, token, key)
            event = clock.now
            reg.revoke(device.name, event)
            for offset, recognized in ((5, True), (10, False), (5, True), (-1, False)):
                clock.now = event + offset
                foreign_rejected(web, token)
                response = web.post(device_path("poll"), headers=headers(token),
                                    json=envelope(key, "poll", device.id, {}))
                (explicit if recognized else core_generic)(response)
                assert (provider.verify_token(token=token) is not None) is recognized
                assert web.get(API + "/local/devices", headers=headers(reg.local_secret)).status_code == 200


def test_pairing_code_lifecycle_is_confined(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, provider):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            for _ in range(2):
                key = SigningKey.generate()
                code = reg.mint("pairing", clock.now)
                assert provider.verify_token(token=code) is not None
                foreign_rejected(web, code)
                response = web.post(device_path("hello"), headers=headers(code),
                                    json=envelope(key, "hello", "pairing", hello(key, tmp_path, "pairing")))
                assert response.status_code == 200, response.text
                assert provider.verify_token(token=code) is None
                foreign_rejected(web, code)
                active_poll(web, relay, reg.active_device("pairing"), response.json()["token"], key)
            stale = reg.mint("stale", clock.now)
            fresh = reg.mint("stale", clock.now)
            assert provider.verify_token(token=stale) is None
            assert provider.verify_token(token=fresh) is not None
            foreign_rejected(web, stale)
            foreign_rejected(web, fresh)
            reg.revoke("stale", clock.now)
            assert provider.verify_token(token=fresh) is None
            foreign_rejected(web, fresh)
            expires = reg.mint("expiring", clock.now)
            control = reg.mint("expiry-control", clock.now)
            clock.advance(599)
            assert provider.verify_token(token=expires) is not None
            foreign_rejected(web, expires)
            key = SigningKey.generate()
            assert web.post(device_path("hello"), headers=headers(control),
                            json=envelope(key, "hello", "expiry-control", hello(key, tmp_path, "expiry-control"))).status_code == 200
            clock.advance()
            assert provider.verify_token(token=expires) is None
            foreign_rejected(web, expires)
            assert web.get(API + "/local/devices", headers=headers(reg.local_secret)).status_code == 200
            key = SigningKey.generate()
            code = reg.mint("control", clock.now)
            assert web.post(device_path("hello"), headers=headers(code),
                            json=envelope(key, "hello", "control", hello(key, tmp_path, "control"))).status_code == 200


@pytest.mark.parametrize("kind", ["device", "local"])
def test_legacy_route_stays_closed_after_disposal(tmp_path, monkeypatch, kind):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, provider):
        with TestClient(app, client=("127.0.0.1", 10)) as web:
            device, bearer, key = paired(reg, tmp_path, now=clock.now)
            token = bearer if kind == "device" else reg.local_secret
            active_poll(web, relay, device, bearer, key)
            assert web.get(API + "/local/devices", headers=headers(reg.local_secret)).status_code == 200
            foreign_rejected(web, token)
            provider.routes.registrations.pop().dispose()
            foreign_rejected(web, token)
            provider.routes.dispose()
            assert web.get(FOREIGN, headers=headers(token)).status_code == 401
            assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200
            assert web.get(UNBOUND, headers=headers(token)).status_code == 401
            assert web.get(UNBOUND, headers=headers(UNBOUND_TOKEN)).status_code == 200
            assert provider.verify_token(token=token) is None
            assert web.get(API + "/local/devices", headers=headers(reg.local_secret)).status_code == 401


@pytest.mark.parametrize("closed", ["missing", "refused", "unloaded"])
@pytest.mark.parametrize("kind", ["device", "pair", "local", "retained"])
def test_closed_provider_rejects_credentials_on_legacy_route(tmp_path, monkeypatch, closed, kind):
    clock = Clock(monkeypatch)
    with plugin_context() as ctx, plugin_context("notice-unbound") as foreign_ctx:
        foreign = ForeignTokenProvider(token=UNBOUND_TOKEN)
        foreign.name = "notice-unbound"
        assert foreign_ctx.register_dashboard_auth_provider(foreign) is not None
        token_auth.register_token_route(UNBOUND)
        if closed == "refused":
            observed = record_routes(ctx, monkeypatch, 5, "none")
        provider = register(MissingMethodContext(ctx) if closed == "missing" else ctx, tmp_path, monkeypatch)
        reg, relay = provider.registry, provider.relay
        device, bearer, key = paired(reg, tmp_path, now=clock.now - 1)
        retired, retained, _ = paired(reg, tmp_path, name="retained", now=clock.now - 1)
        reg.revoke(retired.name, clock.now)
        tokens = dict(device=bearer, pair=reg.mint("pending", clock.now),
                      local=reg.local_secret, retained=retained)
        if closed == "refused":
            assert len(observed.handles) == 4 and all(not handle.active for handle in observed.handles)
            assert not provider.routes.registrations
        with mounted(tmp_path, relay=relay, provider=provider) as (app, *_):
            app.get(UNBOUND)(lambda: {"provider": "foreign"})
            with TestClient(app, client=("127.0.0.1", 10)) as web:
                if closed == "unloaded":
                    active_poll(web, relay, device, bearer, key)
                    ctx._manager.unload()
                assert not provider.routes.enabled and get_provider("dirtside") is provider
                assert web.get(UNBOUND, headers=headers(UNBOUND_TOKEN)).status_code == 200
                response = web.get(UNBOUND, headers=headers(tokens[kind]))
                assert response.status_code == 401, response.text
                assert response.json() == {"error": "unauthenticated", "detail": "Unauthorized"}
                assert provider.verify_token(token=tokens[kind]) is None
