"""Relay wire labels cannot supply native command authority."""
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from gateway.config import Platform
from gateway.relay.ws_transport import _event_from_wire
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from gateway.session_context import clear_session_vars
from hermes_cli.plugin_command_dispatch import invoke_plugin_command
from hermes_cli.plugin_session import session_surface

from dirtside.access import Access
from dirtside.commands import Commands
from dirtside.registry import Registry
from dirtside.relay import Relay


def context():
    return SimpleNamespace(session_surface=session_surface, get_config=lambda key, default=None: default)


@contextmanager
def bound(source, session_id="canonical-session"):
    ctx = SimpleNamespace(source=source, session_key="agent:main:local:route", session_id=session_id)
    tokens = GatewayRunner._set_session_env(SimpleNamespace(adapters={}), ctx)
    try:
        yield
    finally:
        clear_session_vars(tokens)


@pytest.mark.parametrize("user", [None, f"uid:{os.getuid()}"])
@pytest.mark.parametrize("chat_id", ["relay-chat", "canonical-session"])
def test_relay_wire_local_cannot_become_host(tmp_path, user, chat_id):
    wire = {"platform": "local", "chat_id": chat_id, "delivered_via_upstream_relay": False}
    if user is not None:
        wire["user_id"] = user
    source = _event_from_wire({"source": wire, "text": "/dirtside"}).source
    assert source.delivered_via_upstream_relay is True
    reg = Registry(tmp_path / "data.db")
    access = Access(context(), owners=["local"])
    command = Commands(context(), reg, Relay(reg), access=access)
    with bound(source):
        assert session_surface() == "local"
        assert access.identity() != "local"
        assert "Sender: local." not in invoke_plugin_command(command, "", source=source)
        assert "--code=" not in invoke_plugin_command(command, "pair private", source=source)
    assert reg.devices() == []


@pytest.mark.parametrize("user", ["", f"uid:{os.getuid()}", f"uid:{os.getuid() + 1}", "sid:host"])
def test_command_source_authority_is_scoped(tmp_path, user):
    reg = Registry(tmp_path / "data.db")
    access = Access(context(), owners=["local"])
    command = Commands(context(), reg, Relay(reg), access=access)
    source = SessionSource(Platform.LOCAL, "canonical-session", user_id=user)
    with bound(source):
        expected = user in ("", f"uid:{os.getuid()}")
        result = invoke_plugin_command(command, "", source=source)
        assert ("Sender: local." in result) is expected
        assert access.identity() != "local"
        assert "Sender: local." not in invoke_plugin_command(command, "")
        assert ("--code=" in invoke_plugin_command(command, "pair native", source=source)) is expected
        assert access.identity() != "local"


@pytest.mark.parametrize("source", [
    None,
    SimpleNamespace(platform=Platform.LOCAL),
    SessionSource(Platform.LOCAL, "canonical-session", delivered_via_upstream_relay=True),
    SessionSource(Platform.LOCAL, "canonical-session", detached_route="remote-route"),
    SessionSource(Platform.TELEGRAM, "canonical-session"),
])
def test_incomplete_or_remote_command_source_is_not_host(tmp_path, source):
    reg = Registry(tmp_path / "data.db")
    command = Commands(context(), reg, Relay(reg))
    with bound(SessionSource(Platform.LOCAL, "canonical-session", user_id=f"uid:{os.getuid()}")):
        assert "Sender: local." not in invoke_plugin_command(command, "", source=source)


def test_command_authority_resets_on_errors_and_overlapping_calls(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    reg = Registry(tmp_path / "data.db")
    access = Access(context())
    command = Commands(context(), reg, Relay(reg), access=access)
    source = SessionSource(Platform.LOCAL, "canonical-session", user_id=f"uid:{os.getuid()}")
    barrier = Barrier(2)

    def status():
        barrier.wait(timeout=5)
        return access.identity()

    command.status = status
    def call(trusted):
        with bound(source):
            result = invoke_plugin_command(command, "", source=source if trusted else None)
            assert access.identity() != "local"
            return result
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(call, trusted) for trusted in (True, False)]
        assert [future.result() == "local" for future in futures] == [True, False]
    def fail():
        assert access.identity() == "local"
        raise RuntimeError("handler failed")
    command.status = fail
    with bound(source):
        with pytest.raises(RuntimeError, match="handler failed"):
            invoke_plugin_command(command, "", source=source)
        assert access.identity() != "local"


@pytest.mark.parametrize("provider", ["basic", "nous", "self-hosted", "session-token", "server-internal"])
@pytest.mark.parametrize("forwarded", [False, True])
def test_core_signins_act_as_host_owner(tmp_path, provider, forwarded):
    import json
    from gateway.owner_identity import host_owner_subject, principal_subject
    identity = {"provider": "local" if forwarded else provider,
                "user_id": "auth:v1:" + json.dumps([provider, "", "alice"]) if forwarded else "alice"}
    if forwarded:
        identity.update(profile_id=str(tmp_path), instance_id="native-ticket", capabilities=[])
    subject = principal_subject(identity)
    assert subject == host_owner_subject() == f"uid:{os.getuid()}"
    source = SessionSource(Platform.LOCAL, "canonical-session", user_id=subject)
    reg = Registry(tmp_path / "data.db")
    with bound(source):
        assert "Sender: local." in invoke_plugin_command(Commands(context(), reg, Relay(reg)), "", source=source)


@pytest.mark.parametrize("platform", ["cli", "tui", "desktop", "acp"])
def test_relay_wire_host_surface_labels_are_not_host(tmp_path, platform):
    source = _event_from_wire({"source": {"platform": platform}}).source
    access = Access(context(), owners=["local"])
    reg = Registry(tmp_path / "data.db")
    with bound(source):
        assert access.identity() != "local"
        command = Commands(context(), reg, Relay(reg), access=access)
        assert "--code=" not in invoke_plugin_command(command, "pair private", source=source)
