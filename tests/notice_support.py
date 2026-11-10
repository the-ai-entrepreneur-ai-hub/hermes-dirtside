"""Independent signed clocks and real core token gates."""
import base64
import time
from contextlib import contextmanager

from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth import TokenPrincipal, token_auth
from nacl.signing import SigningKey
from network_support import SessionTokenProvider, mounted
from route_support import plugin_context, register
from test_routes import API, headers, hello

from dirtside.protocol import canonical, parse_hello, sign

FOREIGN = "/api/plugins/notice-foreign/action"
FOREIGN_TOKEN = "foreign-notice-test-token"
UNBOUND = "/api/notice-unbound/action"
UNBOUND_TOKEN = "unbound-notice-test-token"


class ForeignTokenProvider(SessionTokenProvider):
    name = "notice-foreign"
    supports_token = True

    def verify_token(self, *, token):
        return TokenPrincipal("foreign", self.name, ("foreign",)) if self.verify_session(access_token=token) else None


class Clock:
    def __init__(self, monkeypatch):
        self.now = int(time.time())
        monkeypatch.setattr(time, "time", lambda: self.now)

    def advance(self, seconds=1):
        self.now += seconds


@contextmanager
def gateway(root, monkeypatch):
    with plugin_context() as ctx:
        provider = register(ctx, root, monkeypatch)
        with mounted(root, gate=True, relay=provider.relay, provider=provider) as (app, registry, relay, module):
            with plugin_context("notice-foreign") as foreign_ctx:
                foreign = ForeignTokenProvider(token=FOREIGN_TOKEN)
                assert foreign_ctx.register_dashboard_auth_provider(foreign) is not None
                assert foreign_ctx.register_dashboard_token_route(
                    FOREIGN, provider=foreign.name, required_scopes=("foreign",)) is not None
                unbound = ForeignTokenProvider(token=UNBOUND_TOKEN)
                unbound.name = "notice-unbound"
                assert foreign_ctx.register_dashboard_auth_provider(unbound) is not None
                token_auth.register_token_route(UNBOUND)
                for path in (FOREIGN, UNBOUND):
                    app.get(path)(lambda: {"provider": "foreign"})
                with TestClient(app) as web:
                    for path, token in ((FOREIGN, FOREIGN_TOKEN), (UNBOUND, UNBOUND_TOKEN)):
                        assert web.get(path).status_code == 401
                        assert web.get(path, headers={"Authorization": "Bearer " + token}).status_code == 200
                yield app, registry, relay, module, provider


def foreign_rejected(web, token):
    for path, own in ((FOREIGN, FOREIGN_TOKEN), (UNBOUND, UNBOUND_TOKEN)):
        response = web.get(path, headers=headers(token))
        assert response.status_code == 401, response.text
        assert response.json() == {"error": "unauthenticated", "detail": "Unauthorized"}
        assert web.get(path, headers=headers(own)).status_code == 200


def envelope(key, kind, sender, body, timestamp=None):
    wire = sign(key, kind, sender, body)
    if timestamp is not None:
        payload = {name: value for name, value in wire.items() if name != "sig"} | {"ts": timestamp}
        wire = payload | {"sig": base64.b64encode(key.sign(canonical(payload)).signature).decode()}
    return wire


def active_poll(web, relay, device, token, key):
    cancel = "r_" + "cd" * 12
    relay.cancels[device.id].add(cancel)
    response = web.post(API + "/device/poll", headers=headers(token),
                        json=envelope(key, "poll", device.id, {"running": []}))
    assert response.status_code == 200, response.text
    assert response.json()["body"]["cancel"] == [cancel] and device.id in relay.last_seen


def retire(registry, device, root, clock, replaced):
    if not replaced:
        registry.revoke(device.name, clock.now)
        return None
    key = SigningKey.generate()
    code = registry.mint(device.name, clock.now)
    return registry.complete_pairing(device.name, parse_hello(hello(key, root, device.name)),
                                     clock.now, code=code)
