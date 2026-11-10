"""Actor authority, legacy fallback and live core dispatch on shared routes."""
import os
from contextvars import Context, copy_context
from types import SimpleNamespace

import pytest
from actor_context import HAS_ACTOR, turn, values
from core_rig import Core
from gateway.platforms.event import MessageEvent
from gateway.session_context import clear_session_vars, get_session_env, set_session_vars
from gateway.session_policy import LocalSessionPolicy, policy_scope
from hermes_cli.plugin_session import session_surface

from dirtside.access import Access
from dirtside.environment import EnvironmentConnectionError

actor_core = pytest.mark.skipif(not HAS_ACTOR, reason="Core has no turn-actor binding or merge signal")


def context():
    return SimpleNamespace(session_surface=session_surface, get_config=lambda key, default=None: default)


@pytest.mark.parametrize("actor", [None, "owner", "other", ""])
def test_public_actor_lookup_distinguishes_none_from_empty(monkeypatch, actor):
    access, device = Access(context()), SimpleNamespace(owner="telegram:owner")
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "owner")
    monkeypatch.delenv("HERMES_SESSION_ACTOR_ID", raising=False)
    assert Context().run(get_session_env, "HERMES_SESSION_ACTOR_ID", None) is None
    assert Context().run(access.identity) == "telegram:owner"
    Context().run(access.require, device)
    if actor is not None:
        monkeypatch.setenv("HERMES_SESSION_ACTOR_ID", actor)
    assert Context().run(get_session_env, "HERMES_SESSION_ACTOR_ID", None) == actor
    expected = "telegram:" + actor if actor else ("telegram:owner" if actor is None else "")
    if not HAS_ACTOR:
        expected = "telegram:owner"
    assert Context().run(access.identity) == expected
    if HAS_ACTOR and actor in ("other", ""):
        with pytest.raises(EnvironmentConnectionError, match="Nothing was run on the server"):
            Context().run(access.require, device)
    else:
        Context().run(access.require, device)


def test_bound_route_fallback_on_older_core(monkeypatch):
    monkeypatch.delenv("HERMES_SESSION_ACTOR_ID", raising=False)
    access = Access(context())
    tokens = set_session_vars(platform="telegram", user_id="owner")
    try:
        assert values() == dict(actor="owner" if HAS_ACTOR else None, route="owner", platform="telegram")
        assert access.identity() == "telegram:owner"
        access.require(SimpleNamespace(owner="telegram:owner"))
        with pytest.raises(EnvironmentConnectionError):
            access.require(SimpleNamespace(owner="telegram:other"))
    finally:
        clear_session_vars(tokens)


@actor_core
@pytest.mark.parametrize("actor", ["owner", "other", ""])
def test_adapter_shared_route_authority_uses_real_core_context(actor):
    access, device = Access(context()), SimpleNamespace(owner="telegram:owner")
    with turn("owner", None, True):
        assert values() == dict(actor="owner", route="", platform="telegram")
        access.require(device)
    with turn(actor, None, True):
        assert values() == dict(actor=actor, route="", platform="telegram")
        assert access.identity() == ("telegram:" + actor if actor else "")
        if actor != "owner":
            with pytest.raises(EnvironmentConnectionError):
                access.require(device)
        else:
            access.require(device)


@actor_core
def test_real_merged_event_clears_actor_in_previously_copied_context():
    access, device = Access(context()), SimpleNamespace(owner="telegram:owner")
    with turn("owner", "owner") as event:
        copied = copy_context()
        copied.run(access.require, device)
        event.absorb_turn_input(MessageEvent("same sender", source=event.source, user_id="owner"))
        assert copied.run(values) == dict(actor="owner", route="owner", platform="telegram")
        copied.run(access.require, device)
        event.absorb_turn_input(MessageEvent("other sender", source=event.source, user_id="other"))
        assert copied.run(values) == dict(actor="", route="owner", platform="telegram")
        assert copied.run(access.identity) == ""
        with pytest.raises(EnvironmentConnectionError):
            copied.run(access.require, device)


@pytest.mark.parametrize("source,surface", [("cli", "cli"), ("tui", "tui"), ("gui", "desktop"), ("acp", "acp")])
@pytest.mark.parametrize("actor", [None, "", "foreign"])
def test_host_policy_keeps_no_user_and_same_uid_rules(tmp_path, monkeypatch, source, surface, actor):
    uid = f"uid:{os.getuid()}"
    policy = LocalSessionPolicy(source, surface, str(tmp_path), None, (), "{}", "{}", "{}",
                                ignore_user_config=True)
    access, device = Access(context()), SimpleNamespace(owner="local")
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "local")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", uid)
    monkeypatch.delenv("HERMES_SESSION_ACTOR_ID", raising=False)
    def check():
        with policy_scope(policy):
            assert access.identity() == "local"
            access.require(device)
    Context().run(check)
    if actor is not None:
        monkeypatch.setenv("HERMES_SESSION_ACTOR_ID", actor)
    def changed():
        with policy_scope(policy):
            assert get_session_env("HERMES_SESSION_ACTOR_ID", None) == actor
            expected = {None: "local", "": "", "foreign": "local:foreign"}[actor] if HAS_ACTOR else "local"
            assert access.identity() == expected
            if HAS_ACTOR and actor is not None:
                with pytest.raises(EnvironmentConnectionError):
                    access.require(device)
            else:
                access.require(device)
    Context().run(changed)


@pytest.mark.parametrize("platform", ["", "cron"])
def test_cron_no_user_rule_does_not_grant_an_identified_actor(monkeypatch, platform):
    access, device = Access(context()), SimpleNamespace(owner="local")
    for name, value in dict(HERMES_SESSION_PLATFORM=platform, HERMES_SESSION_USER_ID="",
                            HERMES_CRON_SESSION="1", HERMES_SESSION_ACTOR_ID="").items():
        monkeypatch.setenv(name, value)
    assert Context().run(access.identity) == "local"
    Context().run(access.require, device)
    monkeypatch.setenv("HERMES_SESSION_ACTOR_ID", "other")
    if HAS_ACTOR:
        assert Context().run(access.identity) != "local"
        with pytest.raises(EnvironmentConnectionError):
            Context().run(access.require, device)
    else:
        Context().run(access.require, device)
    assert Context().run(Access().identity) == "local"


def test_direct_acp_binding_still_needs_surface_provenance(tmp_path):
    access, device = Access(context()), SimpleNamespace(owner="local")
    tokens = set_session_vars(session_key="editor", session_id="editor", cwd=str(tmp_path), cron_session="")
    try:
        assert values() == dict(actor="" if HAS_ACTOR else None, route="", platform="")
        policy = LocalSessionPolicy("acp", "acp", str(tmp_path), None, (), "{}", "{}", "{}",
                                    ignore_user_config=True)
        with policy_scope(policy):
            access.require(device)
        with pytest.raises(EnvironmentConnectionError):
            access.require(device)
        assert Access().identity() == "local"
    finally:
        clear_session_vars(tokens)


def test_configured_owner_privilege_uses_actor_not_route(monkeypatch):
    access, device = Access(context(), owners=["telegram:admin"]), SimpleNamespace(owner="telegram:owner")
    for name, value in dict(HERMES_SESSION_PLATFORM="telegram", HERMES_SESSION_USER_ID="admin",
                            HERMES_SESSION_ACTOR_ID="admin").items():
        monkeypatch.setenv(name, value)
    Context().run(access.require, device)
    assert Context().run(access.may_pair)
    monkeypatch.setenv("HERMES_SESSION_ACTOR_ID", "other")
    if HAS_ACTOR:
        assert not Context().run(access.may_pair)
        with pytest.raises(EnvironmentConnectionError):
            Context().run(access.require, device)
    else:
        assert Context().run(access.may_pair)
        Context().run(access.require, device)


@pytest.mark.parametrize("source", ["cli", "tui", "desktop", "acp", "gui"])
def test_no_user_host_source_fallback_does_not_override_chat_platform(source):
    access, device = Access(context()), SimpleNamespace(owner="local")
    tokens = set_session_vars(source=source)
    try:
        assert values() == dict(actor="" if HAS_ACTOR else None, route="", platform="")
        access.require(device)
        set_session_vars(source=source, platform="telegram")
        assert access.identity() == ""
        with pytest.raises(EnvironmentConnectionError):
            access.require(device)
    finally:
        clear_session_vars(tokens)


@pytest.mark.parametrize("actor", ["", f"uid:{os.getuid()}", f"uid:{os.getuid() + 1}"])
def test_native_command_source_is_still_required_for_local_actor(tmp_path, monkeypatch, actor):
    from gateway.config import Platform
    from gateway.session import SessionSource
    from hermes_cli.plugin_command_dispatch import invoke_plugin_command
    from dirtside.commands import Commands
    from dirtside.registry import Registry
    from dirtside.relay import Relay
    monkeypatch.setattr("dirtside.commands.time", SimpleNamespace(time=lambda: 100))
    for name, value in dict(HERMES_SESSION_PLATFORM="local", HERMES_SESSION_USER_ID=f"uid:{os.getuid()}",
                            HERMES_SESSION_ACTOR_ID=f"uid:{os.getuid()}").items():
        monkeypatch.setenv(name, value)
    registry, access = Registry(tmp_path / "data.db"), Access(context(), owners=["local"])
    commands = Commands(context(), registry, Relay(registry), access=access)
    source = SessionSource(Platform.LOCAL, "native", user_id=f"uid:{os.getuid()}")
    def invoke(raw, native=None):
        return Context().run(lambda: invoke_plugin_command(commands, raw, source=native))
    assert "--code=" in invoke("pair positive", source)
    monkeypatch.setenv("HERMES_SESSION_ACTOR_ID", actor)
    assert "--code=" not in invoke("pair unscoped")
    admitted = actor == f"uid:{os.getuid()}" if HAS_ACTOR else True
    assert ("--code=" in invoke("pair scoped", source)) is admitted
    assert "--code=" not in invoke("pair after")


def step(method, **params):
    return dict(method=method, params=params)


@actor_core
@pytest.mark.parametrize("worker", [False, True])
def test_shared_actor_real_terminal_file_hook_and_frozen_section(tmp_path, worker):
    host, device = tmp_path / "host", tmp_path / "device"
    host.mkdir()
    device.mkdir()
    (host / "proof").write_text("server-only")
    (device / "proof").write_text("device-only")
    with Core(tmp_path / "gateway", user_home=host) as owner:
        owner.call("fake_device", root=str(device), owner="telegram:owner")
        owner.call("target", session="shared", name="fake")
        from contextlib import nullcontext
        with Core(owner.home, env=owner.env, worker=True) if worker else nullcontext(owner) as core:
            def call(actor, steps):
                return core.call("actor_sequence", session="shared", actor=actor, route=None, shared=True, steps=steps)
            steps = [step("turn_facts"), step("identity"), step("terminal", args=dict(command="pwd")),
                     step("file", tool="read_file", args=dict(path="proof")),
                     step("prompt", snapshot="owner"), step("unbound")]
            facts, identity, terminal, file, prompt, unbound = call("owner", steps)
            assert identity == dict(actor="owner", route="", platform="telegram", sender="telegram:owner")
            assert terminal["output"] == str(device.resolve()) and "device-only" in str(file)
            assert "fake" in str(facts) and "fake" in str(prompt)
            assert unbound == dict(actor=None, route="", platform="")
            before = owner.http("GET", "/requests").json()
            for actor in ("other", ""):
                denied = call(actor, [step("turn_facts"), step("terminal", args=dict(command="touch forbidden")),
                                     step("file", tool="read_file", args=dict(path="proof")),
                                     step("prompt", snapshot=actor or "missing")])
                assert "Nothing was run on the server" in str(denied[1])
                assert "Nothing was run on the server" in str(denied[2])
                assert "device-only" not in str(denied[2]) and "server-only" not in str(denied[2])
                assert not denied[0] and not denied[3]
                assert owner.http("GET", "/requests").json() == before
                assert not (host / "forbidden").exists() and not (device / "forbidden").exists()


@actor_core
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("joined", ["owner", "other"])
def test_merged_turn_real_dispatch_keeps_route_but_not_first_actor(tmp_path, joined, explicit):
    host, device = tmp_path / "host", tmp_path / "device"
    host.mkdir()
    device.mkdir()
    (host / "proof").write_text("server-only")
    (device / "proof").write_text("device-only")
    with Core(tmp_path / "gateway", user_home=host) as core:
        core.call("fake_device", root=str(device), owner="telegram:owner")
        if explicit:
            core.call("target", session="merged", name="fake")
        else:
            assert core.call("reload", default_target="fake")["enabled"]
        result = core.call("actor_sequence", session="merged", actor="owner", route="owner", steps=[
            step("turn_facts"), step("prompt", snapshot="before"),
            step("terminal", args=dict(command="pwd")), step("file", tool="read_file", args=dict(path="proof")),
            step("request_ids"),
            step("absorb", joined=joined), step("identity"),
            step("terminal", args=dict(command="pwd; cat proof; printf joined > joined")),
            step("file", tool="read_file", args=dict(path="proof")), step("request_ids"),
            step("prompt", snapshot="before")])
        assert "fake" in str(result[:2])
        assert result[2]["output"] == str(device.resolve()) and "device-only" in str(result[3])
        actor = "owner" if joined == "owner" else ""
        assert result[5] == dict(actor=actor, route="owner", platform="telegram")
        assert result[6]["sender"] == ("telegram:owner" if actor else "")
        if actor:
            assert result[7]["exit_code"] == 0 and (device / "joined").read_text() == "joined"
            assert str(device.resolve()) in result[7]["output"] and "device-only" in result[7]["output"]
            assert "device-only" in str(result[8]) and result[9] != result[4]
        else:
            assert "no single sender" in str(result[7]) and "new message" in str(result[7])
            assert "Nothing was run on the server" in str(result[7])
            assert "Nothing was run on the server" in str(result[8]) and "device-only" not in str(result[8])
            assert "server-only" not in str(result[7:9])
            assert result[9] == result[4] and result[4]
            assert not (device / "joined").exists()
        assert result[10] == result[1] and "Commands run there, not on the server." in str(result[10])
        assert not (host / "joined").exists()


@actor_core
def test_shared_slash_commands_and_picker_act_for_current_actor(tmp_path):
    root = tmp_path / "device"
    root.mkdir()
    with Core(tmp_path / "gateway") as core:
        for actor in ("owner", "other"):
            core.call("fake_device", name=actor + "-device", root=str(root), owner="telegram:" + actor)
        def slash(actor, raw="", command="dirtside", **extra):
            return core.call("actor_sequence", session="commands", actor=actor, shared=True, slash=True,
                             steps=[step("slash", raw_args=raw, command=command, **extra)])[0]
        for actor, foreign in (("owner", "other"), ("other", "owner")):
            own, other = actor + "-device", foreign + "-device"
            assert own in slash(actor, "devices") and other not in slash(actor, "devices")
            assert "now targets " + own in slash(actor, "use " + own)
            assert "not paired" in slash(actor, "use " + other)
            assert "Landed on " + own in slash(actor, own, "land")
            assert "not paired" in slash(actor, other, "land")
            picker = slash(actor, "", "land", choice=own)
            assert picker["questions"][0][1] == [own, "server"] and own in picker["reply"]
            refused = slash(actor, "", "land", choice=other)
            assert "not offered" in refused["reply"]
            assert slash(actor, "", "orbit") == "Back in orbit. Commands run on the server."
            assert "--code=" in slash(actor, "pair pending-" + actor)
            assert "unavailable" in slash(foreign, "pair pending-" + actor)
            assert "No paired device" in slash(foreign, "revoke " + own)
            assert own in slash(actor, "devices")
        assert "Revoked owner-device" in slash("owner", "revoke owner-device")
        assert "owner-device" not in slash("owner", "devices")
        assert "Revoked other-device" in slash("other", "revoke other-device")
