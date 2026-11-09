"""Token-only device recognition and exact-path token route registration."""
import hmac
import logging
import time
from contextlib import suppress
from hermes_cli.dashboard_auth import DashboardAuthProvider, TokenPrincipal
from . import model, protocol
from .local import LocalAPI
from .environment import EnvironmentConnectionError
from .client import process_started

DEVICE_PATHS = tuple(f"/api/plugins/dirtside/device/{kind}" for kind in ("pair", "poll", "chunk", "result"))
LOCAL_PATHS = tuple(f"/api/plugins/dirtside/local/{kind}" for kind in ("exec", "stream", "kill", "devices", "requests"))

class TokenRoutes:
    def __init__(self):
        self.enabled, self.registrations = False, []

    def dispose(self):
        self.enabled = False
        while self.registrations:
            with suppress(Exception):
                self.registrations.pop().dispose()

class DirtsideDeviceAuth(DashboardAuthProvider):
    name = "dirtside"
    display_name = "Dirtside device"
    supports_token = True
    interactive_login = False
    supports_session = False
    model, protocol = model, protocol
    connection_error = EnvironmentConnectionError
    process_started = staticmethod(process_started)

    def __init__(self, registry, relay=None, default_target="server"):
        self.registry, self.relay, self.default_target = registry, relay, default_target
        self.routes = TokenRoutes()
        self.local = LocalAPI(registry, relay, lambda: self.routes.enabled)

    def target_name(self, key):
        from .provider import Access, OnDevice, resolve_target
        target = resolve_target(key, False, self.default_target, self.registry, self.relay,
                                require_contact=False, access=Access(owners=list(self.relay.access.owners)))
        return target.device.name if isinstance(target, OnDevice) else "server"

    def verify_token(self, *, token):
        if hmac.compare_digest(token.encode(), self.registry.local_secret.encode()):
            return TokenPrincipal("local", self.name, ("dirtside-local",))
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

def _legacy_routes():
    # Pending public token-route seam; retain released-core exact-path registration.
    from hermes_cli.dashboard_auth.token_auth import register_token_route
    for path in DEVICE_PATHS + LOCAL_PATHS:
        register_token_route(path)

def register_device_routes(ctx):
    routes = TokenRoutes()
    try:
        if hasattr(ctx, "register_dashboard_token_route"):
            for path in DEVICE_PATHS + LOCAL_PATHS:
                scope = "dirtside-local" if path in LOCAL_PATHS else "dirtside"
                handle = ctx.register_dashboard_token_route(path, provider="dirtside", required_scopes=(scope,))
                if handle is None:
                    raise RuntimeError("token route refused")
                routes.registrations.append(handle)
        else:
            _legacy_routes()
        ctx.on_unload(routes.dispose)
        routes.enabled = True
    except Exception:
        routes.dispose()
        logging.getLogger(__name__).warning(
            "Dirtside token-route registration refused; device and local routes are disabled.")
    return routes
