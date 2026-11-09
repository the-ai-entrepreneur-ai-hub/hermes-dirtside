"""Real loopback listener shared by network tests."""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from hermes_cli.dashboard_auth.middleware import gated_auth_middleware
from hermes_cli.dashboard_auth.registry import (
    register_global_provider, restore_registration, snapshot_registration,
)
from hermes_cli.dashboard_auth.token_auth import token_auth_middleware
from hermes_cli.web_server_dashboard import _discover_dashboard_plugins, _mount_one_plugin_api
from plugins.dashboard_auth.session_token import SessionTokenProvider

from dirtside.auth import DirtsideDeviceAuth, register_device_routes
from dirtside.registry import Registry
from dirtside.relay import Relay

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_TOKEN = "local-test-dashboard-session"


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        threading.Event().wait(0.01)
    raise AssertionError("network test did not reach its expected state")


@contextmanager
def listening(app, host="127.0.0.1", ipv6_only=None, connect_host=None):
    listener = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    if ipv6_only is not None:
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, int(ipv6_only))
    listener.bind((host, 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off", timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        until(lambda: server.started)
        connect_host = connect_host or host
        connect_host = f"[{connect_host}]" if ":" in connect_host else connect_host
        yield f"http://{connect_host}:{listener.getsockname()[1]}"
    finally:
        bound = getattr(getattr(app, "state", None), "dirtside_relay", None)
        if bound is not None:
            for device in bound.registry.devices():
                bound.revoke(device.id)
        server.should_exit = True
        thread.join(4)
        listener.close()
        assert not thread.is_alive()


@contextmanager
def mounted(root, gate=True, relay=None):
    registry = relay.registry if relay is not None else Registry(root / "data.db")
    relay = relay or Relay(registry)
    providers = [DirtsideDeviceAuth(registry, relay), SessionTokenProvider(token=DESKTOP_TOKEN)]
    previous = [(p, snapshot_registration(p.name)) for p in providers]
    for provider in providers:
        register_global_provider(provider)
    register_device_routes()
    app = FastAPI()
    app.state.auth_required = gate
    app.state.dirtside_relay = relay
    app.middleware("http")(gated_auth_middleware)
    app.middleware("http")(token_auth_middleware)
    # The review checkout can sit beside another plugin with the same name.
    with tempfile.TemporaryDirectory(prefix="dirtside-discovery-") as isolated:
        (Path(isolated) / "dirtside").symlink_to(ROOT, target_is_directory=True)
        plugins = _discover_dashboard_plugins([(Path(isolated), "user")])
        for plugin in plugins:
            plugin["_dir"] = str(Path(plugin["_dir"]).resolve())
    entry = next(p for p in plugins if p["name"] == "dirtside")
    assert Path(entry["_dir"]) == ROOT / "dashboard"
    assert _mount_one_plugin_api(app, entry, {"dirtside"}, set())
    module = sys.modules["hermes_dashboard_plugin_dirtside"]
    try:
        yield app, registry, relay, module
    finally:
        for device in registry.devices():
            relay.revoke(device.id)
        module.POLL_POOL.shutdown(wait=True)
        module.FEED_POOL.shutdown(wait=True)
        for provider, old in previous:
            restore_registration(provider.name, provider, old)


@contextmanager
def subprocess_agent(cfg, root):
    for name in ("home", "tmp", "runtime"):
        (root / name).mkdir(parents=True, exist_ok=True)
    cfg.save(root / "dirtside" / "device.json")
    core = os.environ.get("HERMES_SRC", str(ROOT.parent / "hermes-agent-main"))
    env = os.environ | dict(HERMES_HOME=str(root), HOME=str(root / "home"), TMPDIR=str(root / "tmp"),
                            HERMES_RUNTIME_DIR=str(root / "runtime"), TERMINAL_TEMP_DIR=str(root / "tmp"),
                            PYTHONPATH=os.pathsep.join((str(ROOT), core)))
    with (root / "process.log").open("w") as log:
        proc = subprocess.Popen([sys.executable, "-m", "dirtside.agent"], cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
