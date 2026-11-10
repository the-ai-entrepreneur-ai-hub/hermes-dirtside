"""Independent signed clocks and real core token gates."""
import base64
import time
from contextlib import contextmanager

from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth import TokenPrincipal, token_auth
from hermes_cli.dashboard_auth.registry import (
    register_global_provider, restore_registration, snapshot_registration,
)
from nacl.signing import SigningKey
from network_support import SessionTokenProvider, mounted
from test_review_token_routes import LegacyContext, PublicContext, register
from test_routes import API, headers, hello

from dirtside.auth import DEVICE_PATHS, LOCAL_PATHS
from dirtside.protocol import canonical, parse_hello, sign

FOREIGN = "/api/notice-foreign/action"
FOREIGN_TOKEN = "foreign-notice-test-token"


class ForeignTokenProvider(SessionTokenProvider):
    name = "notice-foreign"
    supports_token = True

    def verify_token(self, *, token):
        return TokenPrincipal("foreign", self.name, ()) if self.verify_session(access_token=token) else None


class Clock:
    def __init__(self, monkeypatch):
        self.now = int(time.time())
        monkeypatch.setattr(time, "time", lambda: self.now)

    def advance(self, seconds=1):
        self.now += seconds


@contextmanager
def gateway(root, monkeypatch, public=False):
    ctx = PublicContext() if public else LegacyContext()
    provider = register(ctx, root, monkeypatch)
    if public:
        # The fake seam records bindings; the released core gate stays unbound.
        for path in DEVICE_PATHS + LOCAL_PATHS:
            token_auth.register_token_route(path)
    with mounted(root, gate=True, relay=provider.relay, provider=provider) as (app, registry, relay, module):
        foreign = ForeignTokenProvider(token=FOREIGN_TOKEN)
        previous = snapshot_registration(foreign.name)
        register_global_provider(foreign)
        token_auth.register_token_route(FOREIGN)
        app.get(FOREIGN)(lambda: {"provider": "foreign"})
        try:
            with TestClient(app) as web:
                assert web.get(FOREIGN).status_code == 401
                assert web.get(FOREIGN, headers={"Authorization": "Bearer " + FOREIGN_TOKEN}).status_code == 200
            yield app, registry, relay, module, provider
        finally:
            restore_registration(foreign.name, foreign, previous)


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
