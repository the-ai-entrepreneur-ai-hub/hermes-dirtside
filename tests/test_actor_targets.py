"""Route-aware no-sender refusals and the listed empty-route default exception."""
import inspect
import os
from contextlib import contextmanager
from contextvars import Context
from types import SimpleNamespace

import pytest
from actor_context import HAS_ACTOR
from core_rig import Core
from gateway.config import GatewayConfig, Platform
from gateway.platforms.event import MessageEvent
from gateway.relay.ws_transport import _event_from_wire
from gateway.run import GatewayRunner
from gateway.session import SessionSource, build_session_context
from gateway.session_context import NON_MESSAGING_SESSION_SURFACES, clear_session_vars, get_session_env, set_session_vars
from gateway.session_policy import LocalSessionPolicy, policy_scope
from nacl.signing import SigningKey
from test_actor_identity import context
from test_registry import paired

from dirtside.access import Access
from dirtside.commands import Commands
from dirtside.environment import EnvironmentConnectionError
from dirtside.model import OnDevice, Server
from dirtside.protocol import DeviceHello
from dirtside.provider import _NON_MESSAGING, resolve_target
from dirtside.registry import Registry


def owned_pair(registry, root, owner):
    registry.mint("owned", 100, owner=owner)
    hello = DeviceHello(bytes(SigningKey.generate().verify_key), "owned", "macOS", "arm64",
                        str(root), str(root), "0.1.0")
    return registry.complete_pairing("owned", hello, 101)[0]


@contextmanager
def listed_turn(kind, root, *, user="owner", shared=False):
    if kind == "relay_local":
        event = _event_from_wire({"source": {"platform": "local", "chat_id": "listed",
                                            "user_id": "owner"}, "text": "first"})
        assert event.source.delivered_via_upstream_relay
    else:
        source = SessionSource(Platform.LOCAL if kind == "canonical_cli" else Platform(kind), "listed",
                               user_id=f"uid:{os.getuid()}" if kind == "canonical_cli" else user,
                               **(dict(shared_session=True, chat_type="group") if shared else {}))
        event = MessageEvent("first", source=source, user_id=source.user_id)
    policy = (LocalSessionPolicy("cli", "cli", str(root), None, (), "{}", "{}", "{}",
                                 ignore_user_config=True) if kind == "canonical_cli" else None)
    with policy_scope(policy):
        params = {"event": event} if "event" in inspect.signature(build_session_context).parameters else {}
        ctx = build_session_context(event.source, GatewayConfig(), **params)
        ctx.session_key = ctx.session_id = "listed"
        tokens = GatewayRunner._set_session_env(SimpleNamespace(adapters={}), ctx)
        try:
            yield event
        finally:
            clear_session_vars(tokens)


@pytest.mark.skipif(not HAS_ACTOR, reason="Core has no turn-actor binding or real merged event")
@pytest.mark.parametrize("kind", ["canonical_cli", "webhook", "api_server", "relay_local"])
@pytest.mark.parametrize("explicit", [False, True])
def test_listed_platform_merge_refuses_a_device_without_server_fallback(tmp_path, kind, explicit):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    with listed_turn(kind, tmp_path) as event:
        sender, route = access.identity(), get_session_env("HERMES_SESSION_USER_ID")
        assert sender and route
        assert sender == ("local" if kind == "canonical_cli" else event.source.platform.value + ":owner")
        device = owned_pair(registry, tmp_path, sender)
        if explicit:
            registry.set_target("listed", device.id)
        def resolve(cron=False):
            return resolve_target("listed", cron, "owned", registry, None, require_contact=False, access=access)
        assert isinstance(resolve(), OnDevice)
        event.absorb_turn_input(MessageEvent("same", source=event.source, user_id=route))
        assert access.identity() == sender and isinstance(resolve(), OnDevice)
        event.absorb_turn_input(MessageEvent("other", source=event.source, user_id="other"))
        assert get_session_env("HERMES_SESSION_USER_ID") == route and access.identity() == ""
        with pytest.raises(EnvironmentConnectionError, match="no single sender") as error:
            resolve()
        assert "Nothing was run on the server." in str(error.value)
        assert "new message" in error.value.retry_hint and "/dirtside use server" in error.value.retry_hint
        if not explicit:
            assert isinstance(resolve(True), Server)
        registry.set_target("listed", "server")
        assert isinstance(resolve(), Server)


def test_listed_platform_named_sender_keeps_its_device_on_every_core(tmp_path):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    with listed_turn("webhook", tmp_path):
        assert access.identity() == "webhook:owner"
        device = owned_pair(registry, tmp_path, access.identity())
        target = resolve_target("listed", False, "owned", registry, None, require_contact=False, access=access)
        assert isinstance(target, OnDevice) and target.device == device


@pytest.mark.parametrize("explicit", [False, True])
def test_unprintable_webhook_sender_refuses_a_chosen_or_default_device(tmp_path, explicit):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    with listed_turn("webhook", tmp_path):
        device = owned_pair(registry, tmp_path, access.identity())
        if explicit:
            registry.set_target("listed", device.id)
        assert isinstance(resolve_target("listed", False, "owned", registry, None,
                          require_contact=False, access=access), OnDevice)
    with listed_turn("webhook", tmp_path, user="owner\x01"):
        assert get_session_env("HERMES_SESSION_USER_ID") == "owner\x01" and access.identity() == ""
        with pytest.raises(EnvironmentConnectionError, match="no single sender") as error:
            resolve_target("listed", False, "owned", registry, None, require_contact=False, access=access)
        assert "Nothing was run on the server." in str(error.value)


@pytest.mark.parametrize("retired", [False, True])
def test_listed_surface_status_uses_the_refusal_not_another_sender_read(tmp_path, monkeypatch, retired):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    with listed_turn("webhook", tmp_path):
        device = owned_pair(registry, tmp_path, access.identity())
        assert isinstance(resolve_target("listed", False, "owned", registry, None,
                          require_contact=False, access=access), OnDevice)
    if retired:
        assert registry.revoke("owned", 102, owner="webhook:owner") == device
    with listed_turn("webhook", tmp_path, user="owner\x01"):
        read, observed = access.identity, []
        def identity():
            observed.append(read())
            return observed[-1]
        monkeypatch.setattr(access, "identity", identity)
        status = Commands(context(), registry, None, "owned", access).status()
        if retired:
            assert "targets an unpaired device" in status and "No device applies" not in status
        else:
            assert "No device applies" in status and "no single sender" in status
            assert "/dirtside use server" in status and "unpaired" not in status
            assert observed == [""]


@pytest.mark.skipif(not HAS_ACTOR, reason="Core has no turn-actor binding or real merged event")
@pytest.mark.parametrize("platform", ["webhook", "api_server", "msgraph_webhook", "local", "telegram"])
def test_merge_with_an_empty_route_keeps_the_listed_default_exception(tmp_path, platform):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    with listed_turn(platform, tmp_path, shared=True) as event:
        sender = access.identity()
        assert sender == platform + ":owner" and get_session_env("HERMES_SESSION_USER_ID") == ""
        device = owned_pair(registry, tmp_path, sender)
        registry.set_target("explicit", device.id)
        def resolve(key="listed"):
            return resolve_target(key, False, "owned", registry, None, require_contact=False, access=access)
        assert isinstance(resolve(), OnDevice) and isinstance(resolve("explicit"), OnDevice)
        event.absorb_turn_input(MessageEvent("other", source=event.source, user_id="other"))
        assert access.identity() == "" and get_session_env("HERMES_SESSION_USER_ID") == ""
        if platform in _NON_MESSAGING:
            assert isinstance(resolve(), Server)
        else:
            with pytest.raises(EnvironmentConnectionError, match="no single sender"):
                resolve()
        with pytest.raises(EnvironmentConnectionError, match="Nothing was run on the server"):
            resolve("explicit")


def test_named_route_without_a_sender_refuses_even_without_an_actor(tmp_path):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    paired(registry, tmp_path, name="fake")
    def check():
        tokens = set_session_vars(platform="", source="", user_id="owner")
        try:
            assert get_session_env("HERMES_SESSION_USER_ID") == "owner" and access.identity() == ""
            with pytest.raises(EnvironmentConnectionError, match="no single sender"):
                resolve_target("named", False, "fake", registry, None, require_contact=False, access=access)
        finally:
            clear_session_vars(tokens)
    Context().run(check)


def test_default_resolution_uses_one_sender_snapshot(tmp_path, monkeypatch):
    registry, access = Registry(tmp_path / "data.db"), Access(context())
    registry.mint("fake", 100, owner="telegram:owner")
    hello = DeviceHello(bytes(SigningKey.generate().verify_key), "fake", "macOS", "arm64",
                        str(tmp_path), str(tmp_path), "0.1.0")
    device, _ = registry.complete_pairing("fake", hello, 101)
    read, observed = access.identity, []
    def identity():
        sender = read()
        observed.append(sender)
        set_session_vars(platform="telegram", user_id="", source="telegram")
        return sender
    monkeypatch.setattr(access, "identity", identity)
    def check():
        tokens = set_session_vars(platform="telegram", user_id="owner", source="telegram")
        try:
            target = resolve_target("turn", False, "fake", registry, None, require_contact=False, access=access)
            assert isinstance(target, OnDevice) and observed == ["telegram:owner"]
            with pytest.raises(EnvironmentConnectionError, match="Nothing was run on the server"):
                access.require(device)
        finally:
            clear_session_vars(tokens)
    Context().run(check)


@pytest.mark.parametrize("platform", sorted(NON_MESSAGING_SESSION_SURFACES)
                         + ["telegram", "discord", "custom_chat", " API_SERVER ", " TeLeGrAm "])
def test_device_default_uses_platform_not_source_for_missing_sender(tmp_path, platform):
    assert _NON_MESSAGING <= NON_MESSAGING_SESSION_SURFACES and len(
        NON_MESSAGING_SESSION_SURFACES - _NON_MESSAGING) == 1
    registry = Registry(tmp_path / "data.db")
    device, _, _ = paired(registry, tmp_path, name="fake")
    access = Access(context())
    def resolve(key="default", cron=False):
        return resolve_target(key, cron, "fake", registry, None, require_contact=False, access=access)
    def check():
        tokens = set_session_vars(platform="", source="cli", user_id="")
        try:
            assert access.identity() == "local" and isinstance(resolve(), OnDevice)
            set_session_vars(platform=platform, source="telegram", user_id="")
            sender = access.identity()
            if sender == "local":
                assert isinstance(resolve(), OnDevice)
            elif platform.strip().lower() in _NON_MESSAGING:
                assert isinstance(resolve(), Server)
            else:
                for key in ("default", "explicit"):
                    if key == "explicit":
                        registry.set_target(key, device.id)
                    with pytest.raises(EnvironmentConnectionError, match="no single sender") as error:
                        resolve(key)
                    assert "Nothing was run on the server." in str(error.value)
                    assert "new message" in error.value.retry_hint and "/dirtside use server" in error.value.retry_hint
            if platform.strip().lower() in _NON_MESSAGING:
                unlabelled = context()
                unlabelled.session_surface = lambda: None
                missing = Access(unlabelled)
                assert get_session_env("HERMES_SESSION_USER_ID") == "" and missing.identity() == ""
                assert isinstance(resolve_target("no-route", False, "fake", registry, None,
                                  require_contact=False, access=missing), Server)
            registry.set_target("server", "server")
            assert isinstance(resolve("server"), Server)
            assert isinstance(resolve("cron", True), Server)
        finally:
            clear_session_vars(tokens)
    Context().run(check)


@pytest.mark.parametrize("platform", ["telegram", "discord"])
def test_missing_messaging_sender_refuses_but_known_non_owner_keeps_server(tmp_path, platform):
    host, device = tmp_path / "host", tmp_path / "device"
    host.mkdir()
    device.mkdir()
    with Core(tmp_path / "gateway", user_home=host) as core:
        core.call("fake_device", root=str(device), owner=platform + ":owner")
        assert core.call("reload", default_target="fake")["enabled"]
        owner = dict(session="shared", platform=platform, user_id="owner", source=platform)
        assert "fake" in str(core.call("turn_facts", **owner))
        assert str(device.resolve()) in core.call("terminal", **owner, args=dict(command="pwd"))["output"]
        before = core.http("GET", "/requests").json()
        missing = dict(owner, user_id="")
        assert "fake" in core.call("slash", **owner, raw_args="devices")
        assert "online" in core.call("slash", **owner, raw_args="devices")
        status = core.call("slash", **missing, raw_args="")
        assert "no device" in status.lower() and "no single sender" in status
        assert "unpaired" not in status and "/dirtside use server" in status
        assert core.call("turn_facts", **missing) == []
        refused = core.call("terminal", **missing, args=dict(command="touch forbidden"))
        assert "no single sender" in str(refused) and "Nothing was run on the server." in str(refused)
        assert "new message" in str(refused) and "/dirtside use server" in str(refused)
        assert not (host / "forbidden").exists() and not (device / "forbidden").exists()
        foreign = dict(owner, user_id="other")
        assert core.call("turn_facts", **foreign) == ["Dirtside target: server. Commands run on the server."]
        result = core.call("terminal", **foreign, args=dict(command="pwd; printf host > known-sender"))
        assert result["exit_code"] == 0 and str(host.resolve()) in result["output"]
        assert (host / "known-sender").read_text() == "host" and not (device / "known-sender").exists()
        assert core.http("GET", "/requests").json() == before
        core.call("target", session="shared", name="server")
        assert core.call("turn_facts", **missing) == ["Dirtside target: server. Commands run on the server."]
        assert core.call("terminal", **missing, args=dict(command="pwd"))["output"] == str(host.resolve())


@pytest.mark.skipif(not HAS_ACTOR, reason="Core has no turn-actor binding or real merged event")
@pytest.mark.parametrize("explicit", [False, True])
def test_real_turn_loop_refuses_after_another_sender_joins(tmp_path, explicit):
    host, device = tmp_path / "host", tmp_path / "device"
    host.mkdir()
    device.mkdir()
    (host / "proof").write_text("server-only")
    (device / "proof").write_text("device-only")
    with Core(tmp_path / "gateway", user_home=host) as core:
        core.call("fake_device", root=str(device), owner="telegram:owner")
        if explicit:
            core.call("target", session="real-turn", name="fake")
        else:
            assert core.call("reload", default_target="fake")["enabled"]
        result = core.call("actor_loop", session="real-turn", wait=120)
        assert result["redirect"] and result["actor"] == "" and result["hook_calls"] == 1
        assert result["response"] == "done" and len(result["tools"]) == 2
        assert str(device.resolve()) in result["tools"][0] and "device-only" in result["tools"][0]
        assert "no single sender" in result["tools"][1] and "Nothing was run on the server." in result["tools"][1]
        assert result["before"] == result["after"] and result["before"]
        assert result["requests"] >= 3 and result["frozen_device_prompt"] and result["start_facts"]
        assert not result["server_line"] and not result["external_connections"]
        assert not (host / "after-merge").exists() and not (device / "after-merge").exists()
