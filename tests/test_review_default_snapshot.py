"""One conversation default across prompt, display, dispatch and recreation."""
import pytest
from core_rig import Core
from fastapi.testclient import TestClient
from network_support import DESKTOP_TOKEN, mounted

from dirtside.model import OnDevice, Server
from dirtside.provider import resolve_target
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_review_name_safety import pair_as
from test_routes import API, headers


def test_desktop_default_uses_local_trust_rule(tmp_path):
    with mounted(tmp_path) as (app, registry, relay, module), TestClient(app) as web:
        device, _, _ = pair_as(registry, relay, tmp_path, "telegram:bob")
        module.auth.default_target = device.name
        assert isinstance(resolve_target("desktop", False, device.name, registry, relay,
                                         require_contact=False), Server)
        path = API + "/sessions/desktop/target"
        assert web.get(path, headers=headers(DESKTOP_TOKEN)).json() == {"target": "server"}
        assert web.put(path, headers=headers(DESKTOP_TOKEN), json={"target": device.name}).status_code == 200
        assert web.get(path, headers=headers(DESKTOP_TOKEN)).json() == {"target": device.name}
        registry.revoke(device.name, 1)
        assert web.get(path, headers=headers(DESKTOP_TOKEN)).status_code == 404


@pytest.mark.parametrize("first", ["prompt", "dispatch"])
@pytest.mark.parametrize("recreate", [False, True])
def test_default_snapshot_survives_reload(tmp_path, first, recreate):
    with Core(tmp_path / "gateway") as core:
        device_root = tmp_path / "device"
        device_root.mkdir()
        core.call("fake_device", name="device", root=str(device_root))
        assert core.call("reload", default_target="device")["enabled"]
        if first == "dispatch":
            assert core.terminal("pwd", session="existing")["output"].strip() == str(device_root)
        prompt = core.call("prompt", session="existing")
        assert "device" in str(prompt) and str(device_root) in str(prompt)
        identity = core.call("state", session="existing")["identity"]
        assert core.call("reload", default_target="server")["enabled"]
        if recreate:
            assert core.call("reap", session="existing")["identity"] is None
        assert core.call("prompt", session="existing") == prompt
        result = core.terminal("pwd", session="existing")
        assert result["exit_code"] == 0 and result["output"].strip() == str(device_root), result
        if identity is not None and not recreate:
            assert core.call("state", session="existing")["identity"] == identity
        assert core.terminal("pwd", session="new")["output"].strip() == core.env["HOME"]
        core.call("target", session="existing", name="server")
        assert core.terminal("pwd", session="existing")["output"].strip() == core.env["HOME"]


def test_default_snapshot_is_shared_with_independent_registry(tmp_path):
    registry = Registry(tmp_path / "data.db")
    relay = Relay(registry)
    device, _, _ = pair_as(registry, relay, tmp_path, "local")
    assert isinstance(resolve_target("existing", False, "server", registry, relay, require_contact=False), Server)
    other = Registry(registry.path)
    target = resolve_target("existing", False, device.name, other, Relay(other), require_contact=False)
    assert isinstance(target, Server)
    assert resolve_target("new", False, device.name, other, Relay(other), require_contact=False).device == device
    other.set_target("existing", device.id)
    assert isinstance(resolve_target("existing", False, "server", other, Relay(other), require_contact=False), OnDevice)
    other.set_target("existing", None)
    assert isinstance(resolve_target("existing", False, device.name, other, Relay(other), require_contact=False), Server)


def test_cron_does_not_snapshot_an_interactive_default(tmp_path):
    registry = Registry(tmp_path / "data.db")
    relay = Relay(registry)
    device, _, _ = pair_as(registry, relay, tmp_path, "local")
    assert isinstance(resolve_target("cron", True, "server", registry, relay, require_contact=False), Server)
    assert resolve_target("cron", False, device.name, registry, relay, require_contact=False).device == device
    assert isinstance(resolve_target("cron", True, device.name, registry, relay, require_contact=False), Server)
    registry.set_target("cron", device.id)
    assert resolve_target("cron", True, "server", registry, relay, require_contact=False).device == device
