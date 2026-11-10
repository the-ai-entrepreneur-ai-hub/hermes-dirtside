"""Pure recognition against the real core dashboard provider contract."""
import hashlib
import sqlite3
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth.base import TokenPrincipal, assert_protocol_compliance
from hermes_cli.dashboard_auth.token_auth import is_token_route
from nacl.signing import SigningKey
from notice_support import Clock, active_poll, envelope, gateway
from route_support import plugin_context

from dirtside.auth import DEVICE_PATHS, DirtsideDeviceAuth, register_device_routes
from dirtside.model import Device, Pending, Revoked
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired
from test_routes import API, headers

PREVIOUS_SCHEMA = """
CREATE TABLE devices (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash BLOB NOT NULL,
 pubkey BLOB, os TEXT, arch TEXT, home TEXT, temp_dir TEXT, agent_version TEXT,
 created_at INTEGER NOT NULL, expires_at INTEGER, revoked_at INTEGER,
 owner TEXT NOT NULL DEFAULT 'local');
CREATE UNIQUE INDEX devices_active_name ON devices(name)
 WHERE revoked_at IS NULL AND pubkey IS NOT NULL;
CREATE TABLE targets (session_key TEXT PRIMARY KEY, target TEXT NOT NULL, set_at INTEGER NOT NULL);
CREATE TABLE session_defaults (session_key TEXT PRIMARY KEY, target TEXT NOT NULL);
CREATE TABLE requests (
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL, session_key TEXT NOT NULL, task_id TEXT NOT NULL,
 state TEXT NOT NULL, preview TEXT NOT NULL, created_at INTEGER NOT NULL,
 finished_at INTEGER, exit_code INTEGER, reason TEXT);
"""


def test_recognizer_has_no_side_effects(tmp_path):
    reg = Registry(tmp_path / "data.db")
    now = int(time.time())
    device, token, _ = paired(reg, tmp_path, now=now)
    code = reg.mint("pending", now)
    relay = Relay(reg)
    provider = DirtsideDeviceAuth(reg, relay)
    with plugin_context() as ctx:
        assert ctx.register_dashboard_auth_provider(provider) is not None
        provider.routes = register_device_routes(ctx)
        assert provider.routes.enabled
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
    with plugin_context() as ctx:
        assert ctx.register_dashboard_auth_provider(provider) is not None
        provider.routes = register_device_routes(ctx)
        assert provider.routes.enabled and all(is_token_route(path) for path in DEVICE_PATHS)
        assert not is_token_route("/api/plugins/dirtside/devices")


def test_previous_schema_migrates_without_reviving_old_bearer(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    active_key, revoked_key = SigningKey.generate(), SigningKey.generate()
    with closing(sqlite3.connect(tmp_path / "data.db")) as database:
        database.executescript(PREVIOUS_SCHEMA)
        for identity, name, key, revoked in (
                ("a" * 32, "legacy-active", active_key, None),
                ("b" * 32, "legacy-revoked", revoked_key, clock.now - 3600)):
            token_hash = hashlib.sha256((name + "-bearer").encode()).digest()
            database.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (identity, name, token_hash, bytes(key.verify_key), "test", "arm64",
                              str(tmp_path), str(tmp_path), "0.1.0", clock.now - 86400, None, revoked, "local"))
        database.commit()
        assert {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            "devices", "targets", "session_defaults", "requests"}
        assert database.execute("SELECT count(*) FROM devices").fetchone()[0] == 2
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, provider), TestClient(app) as web:
        assert reg._connection().execute(
            "SELECT name FROM sqlite_master WHERE name='retired_credentials'").fetchone() is not None
        assert reg._connection().execute("SELECT count(*) FROM devices").fetchone()[0] == 2
        revoked = reg.credential_for("legacy-revoked-bearer", clock.now, include_revoked=True)
        assert isinstance(revoked, Revoked) and revoked.revoked_at == clock.now - 3600
        assert provider.verify_token(token="legacy-revoked-bearer") is None
        response = web.post(API + "/device/poll", headers=headers("legacy-revoked-bearer"),
                            json=envelope(revoked_key, "poll", revoked.id, {"running": []}))
        assert response.status_code == 401
        assert response.json() == {"error": "unauthenticated", "detail": "Unauthorized"}
        active = reg.active_device("legacy-active")
        assert active.id == "a" * 32 and provider.verify_token(token="legacy-active-bearer") is not None
        active_poll(web, relay, active, "legacy-active-bearer", active_key)
