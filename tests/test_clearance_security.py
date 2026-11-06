"""Regression checks for ownership, default targets and reserved device names."""
import json
import time
from types import SimpleNamespace

import pytest
from core_rig import Core, install
from fastapi.testclient import TestClient
from gateway.session_context import clear_session_vars, set_session_vars
from nacl.signing import SigningKey
from network_support import mounted

import dirtside
from dirtside import cli
from dirtside.commands import Commands
from dirtside.environment import EnvironmentConnectionError
from dirtside.provider import DirtsideProvider
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_owner_correction import recorded
from test_registry import paired, request
from test_routes import API, headers, hello


@pytest.mark.parametrize("gate", [False, True])
@pytest.mark.parametrize("kind", ["pair", "poll", "chunk", "result"])
@pytest.mark.parametrize("credential", ["unknown", "valid"])
def test_rejected_device_traffic_cannot_replace_owner(tmp_path, gate, kind, credential):
    with mounted(tmp_path, gate=gate) as (app, registry, relay, _):
        device, token, _ = paired(registry, tmp_path, now=int(time.time()))
        code = registry.mint("pending", int(time.time()))
        handle = relay.submit(request(device))
        recorded(registry, origin="http://127.0.0.1:8120")
        path = registry.path.with_name("owner.json")
        before, history = path.read_bytes(), registry.recent(10)
        bearer = ("unknown" if credential == "unknown" else code if kind == "pair" else token)
        try:
            with TestClient(app, base_url="http://127.0.0.1:8121") as client:
                response = client.post(API + "/device/" + kind, headers=headers(bearer), content=b"{")
            assert response.status_code == (401 if credential == "unknown" else 400)
            assert path.read_bytes() == before
            assert relay._owner_pid is None
            assert registry.recent(10) == history
        finally:
            handle.kill()
            handle.stdout.close()


@pytest.mark.parametrize("state", ["missing", "revoked", "offline"])
def test_default_device_cannot_execute_on_server(tmp_path, state):
    registry = Registry(tmp_path / "data.db")
    device, _, _ = paired(registry, tmp_path)
    if state == "revoked":
        registry.revoke(device.name, int(time.time()))
    default = "missing" if state == "missing" else device.name
    provider = DirtsideProvider(registry, Relay(registry), default)
    marker, env = tmp_path / "must-not-run", None
    tokens = set_session_vars(session_key="default-target")
    try:
        with pytest.raises(EnvironmentConnectionError):
            env = provider.create_environment(cwd=str(tmp_path), timeout=5)
            env.execute("printf forbidden > must-not-run")
        assert not marker.exists() and registry.recent(10) == []
    finally:
        if env is not None:
            env.cleanup()
        clear_session_vars(tokens)


@pytest.mark.parametrize("cron", ["", "1"])
def test_status_agrees_with_unpaired_default_and_cron(tmp_path, cron):
    registry = Registry(tmp_path / "data.db")
    commands = Commands(SimpleNamespace(), registry, Relay(registry), "missing")
    tokens = set_session_vars(session_key="status", cron_session=cron)
    try:
        target = "server" if cron else "an unpaired device"
        assert commands("") == f"This conversation targets {target}. Online devices: none."
    finally:
        clear_session_vars(tokens)


def test_reserved_server_name_cannot_mint_pairing(tmp_path):
    registry = Registry(tmp_path / "data.db")
    with pytest.raises(ValueError, match="reserved"):
        registry.mint("server", int(time.time()))
    with mounted(tmp_path, gate=False, relay=Relay(registry)) as (app, *_), TestClient(app) as client:
        assert client.post(API + "/pairing", json={"name": "server"}).status_code == 400
    assert registry.devices() == []


def test_invalid_signature_cannot_publish_first_owner(tmp_path):
    with mounted(tmp_path, gate=False) as (app, registry, relay, module), TestClient(app) as client:
        key = SigningKey.generate()
        code = registry.mint("device", int(time.time()))
        body = hello(key, tmp_path)
        wire = module.wire.sign(SigningKey.generate(), "hello", "device", body)
        response = client.post(API + "/device/pair", headers=headers(code), json=wire)
        assert response.status_code == 400
        assert not registry.path.with_name("owner.json").exists()
        assert relay._owner_pid is None


def test_pairing_cli_reserves_server_before_network(monkeypatch, capsys):
    def no_network(**kwargs):
        pytest.fail("a reserved name must be refused before sending the pairing code")
    monkeypatch.setattr(cli.httpx, "Client", no_network)
    args = SimpleNamespace(dirtside_action="pair", gateway_url="https://gateway.example",
                           name="server", code="test-code")
    assert cli.handle(args) == 1
    assert "Pairing failed." in capsys.readouterr().out


@pytest.mark.parametrize("default", ["", None])
def test_empty_default_is_shared_as_server_at_registration(tmp_path, monkeypatch, default):
    captured = {}
    ctx = SimpleNamespace(
        get_config=lambda name, fallback: default,
        register_terminal_environment_provider=lambda value: captured.update(provider=value),
        register_dashboard_auth_provider=lambda value: captured.update(auth=value),
        register_command=lambda name, value, **kwargs: captured.update(commands=value),
        register_system_prompt_section=lambda name, value, **kwargs: captured.update(prompt=value.__self__),
        register_cli_command=lambda *args: None,
    )
    monkeypatch.setattr(dirtside, "plugin_data_dir", lambda name: tmp_path)
    dirtside.register(ctx)
    try:
        assert captured["provider"]._default_target == "server"
        assert all(captured[name].default_target == "server" for name in ("auth", "commands", "prompt"))
    finally:
        captured["provider"]._relay._client.http.close()


@pytest.mark.parametrize("default", ["", None])
@pytest.mark.parametrize("cron", ["", "1"])
def test_empty_yaml_default_runs_on_server_through_core(tmp_path, default, cron):
    home = tmp_path / "core"
    env = install(home)
    path = home / "config.yaml"
    config = json.loads(path.read_text())
    config["plugins"]["entries"]["dirtside"]["settings"]["default_target"] = default
    path.write_text(json.dumps(config) + "\n")
    with Core(home, env=env) as core:
        result = core.call("terminal", session="empty-default", cron=cron,
                           args={"command": "printf normalized-default", "timeout": 5})
        assert result["exit_code"] == 0 and result["output"] == "normalized-default", result
        assert result["cwd"] == str((home / "user").resolve())
        assert core.call("slash", session="empty-default", cron=cron, raw_args="") == (
            "This conversation targets server. Online devices: none.")
        assert core.call("prompt", session="empty-default", cron=cron) == []
        assert core.http("GET", "/sessions/empty-default/target").json() == {"target": "server"}
