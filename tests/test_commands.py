"""Bound chat handlers use real registry, relay and conversation context."""
import shlex
import time
from types import SimpleNamespace

import pytest
from gateway.session_context import clear_session_vars, set_session_vars

from dirtside.commands import USAGE, Commands
from dirtside.model import Pending
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired, request


@pytest.fixture
def commands(tmp_path):
    registry = Registry(tmp_path / "data.db")
    relay = Relay(registry)
    handler = Commands(SimpleNamespace(ask_choice=lambda question, choices: None), registry, relay)
    tokens = set_session_vars(session_key="telegram:42", session_id="different-id")
    try:
        yield handler
    finally:
        clear_session_vars(tokens)


def test_status_and_device_states(commands, tmp_path):
    assert commands("") == "This conversation targets server. Online devices: none. Sender: local."
    assert commands("devices") == "No devices are paired."
    device, _, _ = paired(commands.registry, tmp_path)
    spare, _, _ = paired(commands.registry, tmp_path, "spare")
    commands.relay.touch(device.id)
    assert commands("devices") == "Paired devices: macbook (macOS, online); spare (macOS, offline)."
    commands("use spare")
    assert commands("") == "This conversation targets spare (macOS, offline). Online devices: macbook. Sender: local."
    commands.registry.revoke(spare.name, int(time.time()))
    assert "unpaired device" in commands("")


def test_use_is_conversation_scoped_and_server_overrides_default(commands, tmp_path):
    device, _, _ = paired(commands.registry, tmp_path)
    commands.default_target = device.name
    reply = commands("use macbook")
    assert "(macOS, offline)" in reply
    assert "applies to this conversation from the next command" in reply
    assert commands.registry.target("telegram:42") == device.id
    assert commands.registry.target("different-id") is None
    commands("use server")
    assert commands.registry.target("telegram:42") == "server"
    assert commands.registry.target("other") is None
    assert commands("").startswith("This conversation targets server.")


def test_server_default_is_not_a_paired_device_named_server(commands, tmp_path):
    device, _, _ = paired(commands.registry, tmp_path)
    with commands.registry._tx() as conn:
        conn.execute("UPDATE devices SET name='server' WHERE id=?", (device.id,))
    assert commands.registry.active_device("server") is not None
    assert commands("").startswith("This conversation targets server.")


@pytest.mark.parametrize("choice", ["macbook", "server", None, "not-offered", "spare"])
def test_use_picker_lists_only_online_devices_and_server(commands, tmp_path, choice):
    online, _, _ = paired(commands.registry, tmp_path)
    paired(commands.registry, tmp_path, "spare")
    commands.relay.touch(online.id)
    questions = []
    def ask(question, choices):
        questions.append((question, choices))
        return choice
    commands.ctx.ask_choice = ask
    reply = commands("use")
    assert questions == [("Where should this conversation run commands?", ["macbook", "server"])]
    expected = {"macbook": online.id, "server": "server"}.get(choice)
    assert commands.registry.target("telegram:42") == expected
    assert ("next command" in reply) == (choice in ("macbook", "server"))


def test_missing_conversation_does_not_ask_or_write(commands):
    tokens = set_session_vars(session_key="", session_id="")
    try:
        assert "No conversation" in commands("use server")
        assert "No conversation" in commands("use")
        assert commands.registry.target("") is None
    finally:
        clear_session_vars(tokens)


def test_pair_returns_exact_cli_and_live_expiring_code(commands):
    before = int(time.time())
    reply = commands("pair laptop")
    prefix, command = reply.split("On the device run: ")
    parts = shlex.split(command)
    assert parts[:7] == ["hermes", "dirtside", "pair", "<gateway-url>", "--name", "laptop", parts[6]]
    assert parts[6].startswith("--code=") and len(parts) == 7
    code = parts[6].removeprefix("--code=")
    assert code in prefix and "10 minutes" in prefix
    credential = commands.registry.credential_for(code, before)
    assert isinstance(credential, Pending) and credential.name == "laptop"
    assert before + 600 <= credential.expires_at <= int(time.time()) + 600
    assert commands.registry.credential_for(code, credential.expires_at) is None


def test_revoke_cancels_live_work_and_pending_pairing(commands, tmp_path):
    device, token, _ = paired(commands.registry, tmp_path)
    commands.relay.touch(device.id)
    commands.registry.set_target("telegram:42", device.id)
    handle = commands.relay.submit(request(device))
    commands.relay.next(device.id, 0)
    assert commands("revoke macbook") == "Revoked macbook and cancelled its live requests."
    assert handle.wait(0) == 130 and handle.stdout.read() == b""
    assert commands.registry.credential_for(token, int(time.time())) is None
    assert not commands.relay.is_online(device.id)
    assert commands.registry.target("telegram:42") == device.id
    code = commands.registry.mint("pending", int(time.time()))
    assert "pending pairing code was revoked" in commands("revoke pending")
    assert commands.registry.credential_for(code, int(time.time())) is None


@pytest.mark.parametrize("raw", ["log", "unknown", "devices extra", "use one two", "pair", "pair ../bad",
                                      "pair UPPER", "revoke", "revoke one two", "use missing"])
def test_invalid_input_never_selects_a_target(commands, raw):
    reply = commands(raw)
    assert isinstance(reply, str) and reply
    assert commands.registry.target("telegram:42") is None
    if raw in ("log", "unknown", "devices extra", "use one two", "revoke", "revoke one two"):
        assert reply == USAGE
