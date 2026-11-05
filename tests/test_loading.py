"""Directory and dashboard loaders must share domain types and one live relay."""
import os
import subprocess
import sys

from network_support import ROOT

RUNTIME_CHECK = """
import base64
import sys
import time
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from agent.terminal_env_registry import get_provider as terminal_provider
from hermes_cli.dashboard_auth import get_provider
from hermes_cli.dashboard_auth.middleware import gated_auth_middleware
from hermes_cli.dashboard_auth.token_auth import token_auth_middleware
from hermes_cli.plugins import PluginManager
from hermes_cli.web_server_dashboard import _discover_dashboard_plugins, _mount_one_plugin_api

root, home = map(Path, sys.argv[1:])
manager = PluginManager()
manifest = next(p for p in manager._scan_directory(root.parent, source="user") if Path(p.path) == root)
manager._load_plugin(manifest)
loaded = manager._plugins[manifest.key or manifest.name]
assert loaded.enabled and not loaded.error, loaded.error
auth = get_provider("dirtside")
assert auth is not None and type(auth).__module__.startswith("hermes_plugins.")
terminal = terminal_provider("dirtside")
assert terminal._relay is auth.relay and terminal._registry is auth.registry
app = FastAPI()
app.state.auth_required = True
app.middleware("http")(gated_auth_middleware)
app.middleware("http")(token_auth_middleware)
entry = next(p for p in _discover_dashboard_plugins([(root.parent, "user")])
             if Path(p["_dir"]) == root / "dashboard")
assert _mount_one_plugin_api(app, entry, {"dirtside"}, set())
api = sys.modules["hermes_dashboard_plugin_dirtside"]
assert api.wire is auth.protocol and api.model is auth.model and api.relay is terminal._relay
try:
    key = SigningKey.generate()
    code = auth.registry.mint("loaded", int(time.time()))
    body = dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name="loaded", os="test",
                arch="arm64", home=str(home), temp_dir=str(home), agent_version="0.1.0")
    with TestClient(app) as client:
        prefix = "/api/plugins/dirtside/device/"
        response = client.post(prefix + "pair", headers={"Authorization": "Bearer " + code},
                               json=api.wire.sign(key, "hello", "loaded", body))
        assert response.status_code == 200
        paired = response.json()
        device = auth.registry.active_device("loaded")
        req = auth.model.ExecRequest("r_" + "ab" * 12, device.id, "chat", "default",
                                     "pwd", "pwd", False, 120, None, str(home))
        handle = auth.relay.submit(req)
        headers = {"Authorization": "Bearer " + paired["token"]}
        response = client.post(prefix + "poll", headers=headers, json=api.wire.sign(key, "poll", device.id, {}))
        assert response.status_code == 200 and response.json()["body"]["exec"]["id"] == req.id
        result = dict(id=req.id, state="finished", exit_code=0, duration_ms=1, truncated=False,
                      reason="", seq=0, data=base64.b64encode(b"loaded").decode())
        response = client.post(prefix + "result", headers=headers,
                               json=api.wire.sign(key, "result", device.id, result))
        assert response.status_code == 200 and handle.wait(0) == 0 and handle.stdout.read() == b"loaded"
    print("Directory registration, shared runtime, signed pairing and dispatch passed.")
finally:
    api.POLL_POOL.shutdown(wait=True)
    manager.unload()
"""


def test_real_directory_registration_and_independent_dashboard_import(tmp_path):
    core = os.environ.get("HERMES_SRC", str(ROOT.parent / "hermes-agent-main"))
    env = os.environ | dict(HERMES_HOME=str(tmp_path), HERMES_RUNTIME_DIR=str(tmp_path / "runtime"),
                            PYTHONPATH=os.pathsep.join((str(ROOT), core)))
    result = subprocess.run([sys.executable, "-c", RUNTIME_CHECK, str(ROOT), str(tmp_path)],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "shared runtime" in result.stdout
