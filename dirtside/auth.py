"""Token-only device recognition and exact-path token route registration."""
import time
from hermes_cli.dashboard_auth import DashboardAuthProvider, TokenPrincipal
from hermes_cli.dashboard_auth.token_auth import register_token_route
from . import model, protocol

DEVICE_PATHS = tuple(f"/api/plugins/dirtside/device/{kind}" for kind in ("pair", "poll", "chunk", "result"))

class DirtsideDeviceAuth(DashboardAuthProvider):
    name = "dirtside"
    display_name = "Dirtside device"
    supports_token = True
    interactive_login = False
    supports_session = False
    model, protocol = model, protocol

    def __init__(self, registry, relay=None, default_target="server"):
        self.registry, self.relay, self.default_target = registry, relay, default_target

    def verify_token(self, *, token):
        credential = self.registry.credential_for(token, int(time.time()))
        return TokenPrincipal(credential.name, self.name, ("dirtside",)) if credential else None

    def start_login(self, *, redirect_uri):
        raise NotImplementedError("device credentials have no login flow")

    def complete_login(self, *, code, state, code_verifier, redirect_uri):
        raise NotImplementedError("device credentials have no login flow")

    def verify_session(self, *, access_token):
        return None

    def refresh_session(self, *, refresh_token):
        raise NotImplementedError("device credentials have no sessions")

    def revoke_session(self, *, refresh_token):
        return None

def register_device_routes():
    for path in DEVICE_PATHS:
        register_token_route(path)
