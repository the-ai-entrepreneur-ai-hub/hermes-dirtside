"""Pure recognition against the real core dashboard provider contract."""
import time
from types import SimpleNamespace

import pytest
from hermes_cli.dashboard_auth.base import TokenPrincipal, assert_protocol_compliance
from hermes_cli.dashboard_auth.token_auth import is_token_route

from dirtside.auth import DEVICE_PATHS, DirtsideDeviceAuth, register_device_routes
from dirtside.model import Device, Pending
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired


def test_recognizer_has_no_side_effects(tmp_path):
    reg = Registry(tmp_path / "data.db")
    now = int(time.time())
    device, token, _ = paired(reg, tmp_path, now=now)
    code = reg.mint("pending", now)
    relay = Relay(reg)
    provider = DirtsideDeviceAuth(reg, relay)
    provider.routes = register_device_routes(SimpleNamespace(on_unload=lambda callback: None))
    changes = reg._connection().total_changes
    for _ in range(2):
        assert provider.verify_token(token=token) == TokenPrincipal(device.name, "dirtside", ("dirtside",))
        assert provider.verify_token(token=code) == TokenPrincipal("pending", "dirtside", ("dirtside",))
        assert provider.verify_token(token="unknown") is None
    assert reg._connection().total_changes == changes
    assert not relay.last_seen and not relay.handles and reg.recent(10) == []
    reg.revoke(device.name, now)
    assert provider.verify_token(token=token) == TokenPrincipal(device.name, "dirtside", ("dirtside",))
    assert reg.credential_for(token, now) is None and not relay.last_seen
    reg.revoke("pending", now)
    assert provider.verify_token(token=code) is None
    expired = reg.mint("expired", now - 601)
    assert provider.verify_token(token=expired) is None


def test_retired_lookup_is_not_active_authority(tmp_path):
    reg, now = Registry(tmp_path / "data.db"), int(time.time())
    device, token, _ = paired(reg, tmp_path, now=now)
    reg.revoke(device.name, now)
    assert reg.credential_for(token, now) is None
    retained = reg.credential_for(token, now, include_revoked=True)
    assert not isinstance(retained, (Device, Pending))
    assert (retained.id, retained.name, retained.pubkey) == (device.id, device.name, device.pubkey)
    assert retained.revoked_at == now
    assert reg.active_device(device.name) is reg.device_by_id(device.id) is None
    assert reg.devices() == []
    pending = reg.mint("pending", now)
    reg.revoke("pending", now)
    expired = reg.mint("expired", now - 601)
    changes = reg._connection().total_changes
    for token in (pending, expired, "unknown", None, b"bytes"):
        assert reg.credential_for(token, now, include_revoked=True) is None
    assert reg._connection().total_changes == changes


def test_core_auth_protocol_and_routes(tmp_path):
    provider = DirtsideDeviceAuth(Registry(tmp_path / "data.db"))
    assert_protocol_compliance(type(provider))
    assert provider.supports_token and not provider.supports_session and not provider.interactive_login
    assert provider.verify_session(access_token="ignored") is None
    assert provider.revoke_session(refresh_token="ignored") is None
    with pytest.raises(NotImplementedError):
        provider.start_login(redirect_uri="https://example.com")
    with pytest.raises(NotImplementedError):
        provider.complete_login(code="", state="", code_verifier="", redirect_uri="")
    with pytest.raises(NotImplementedError):
        provider.refresh_session(refresh_token="")
    provider.routes = register_device_routes(SimpleNamespace(on_unload=lambda callback: None))
    assert all(is_token_route(path) for path in DEVICE_PATHS)
    assert not is_token_route("/api/plugins/dirtside/devices")
