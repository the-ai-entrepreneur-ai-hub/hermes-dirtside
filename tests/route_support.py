"""Real launch-owned contexts and discovered dashboard mounts for route tests."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import dirtside
from hermes_cli.dashboard_auth import get_provider, token_auth
from hermes_cli.dashboard_auth.registry import restore_registration, snapshot_registration
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
from hermes_constants import get_hermes_home, hermes_home_key

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def plugin_context(name="dirtside"):
    directory = get_hermes_home() / "plugins" / name
    if not directory.exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        if name == "dirtside":
            directory.symlink_to(ROOT, target_is_directory=True)
        else:
            (directory / "dashboard").mkdir(parents=True)
            (directory / "dashboard/manifest.json").write_text("{}", encoding="utf-8")
    manager = PluginManager(scope_key=hermes_home_key())
    ctx = PluginContext(PluginManifest(name=name, path=str(directory)), manager)
    previous = snapshot_registration(name)
    paths, policies = set(token_auth._token_routes), dict(token_auth._token_route_policies)
    try:
        yield ctx
    finally:
        manager.unload(ctx.manifest)
        manager._evict_stale_persistent_registrations()
        restore_registration(name, snapshot_registration(name), previous)
        assert all(policy.registration.plugin_key != ctx.plugin_id or policies.get(path) is policy
                   for path, policy in token_auth._token_route_policies.items())
        token_auth._token_routes.clear()
        token_auth._token_routes.update(paths)


def register(ctx, root, monkeypatch):
    monkeypatch.setattr("plugins.plugin_storage.plugin_data_dir", lambda _: root)
    dirtside.register(ctx)
    ctx._manager._evict_stale_persistent_registrations()
    return get_provider("dirtside")


def record_routes(ctx, monkeypatch, fail_at=None, refusal="raise"):
    observed = SimpleNamespace(calls=[], handles=[])
    real = ctx.register_dashboard_token_route
    def register_route(path, *, provider, required_scopes=()):
        observed.calls.append((path, provider, required_scopes))
        if len(observed.calls) == fail_at:
            if refusal == "none":
                return None
            raise RuntimeError("registration detail must not be logged")
        handle = real(path, provider=provider, required_scopes=required_scopes)
        assert handle is not None
        observed.handles.append(handle)
        return handle
    monkeypatch.setattr(ctx, "register_dashboard_token_route", register_route)
    return observed


class MissingMethodContext:
    """Negative control only; every other operation reaches the real context."""
    def __init__(self, ctx):
        self.ctx = ctx

    def __getattr__(self, name):
        if name == "register_dashboard_token_route":
            raise AttributeError(name)
        return getattr(self.ctx, name)
