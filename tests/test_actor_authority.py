"""Bound senders cannot be replaced by environment or no-user host rules."""
import inspect
import json
import os
import subprocess
import sys
from contextlib import nullcontext
from contextvars import Context, copy_context
from pathlib import Path
from types import SimpleNamespace

import pytest
from actor_context import HAS_ACTOR, turn, values
from gateway.config import Platform
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource
from gateway.session_context import clear_session_vars, set_session_vars
from gateway.session_policy import LocalSessionPolicy, policy_scope
from test_actor_identity import context
from test_review_relay_local import bound

from dirtside.access import Access
from dirtside.environment import EnvironmentConnectionError

actor_core = pytest.mark.skipif(not HAS_ACTOR, reason="Core has no turn-actor binding or merge signal")


@pytest.mark.parametrize("platform", ["telegram", "local"])
def test_bound_turn_ignores_planted_actor_environment(tmp_path, monkeypatch, platform):
    import dirtside.access as module
    user = "mallory" if platform == "telegram" else f"uid:{os.getuid() + 1}"
    planted = "owner" if platform == "telegram" else f"uid:{os.getuid()}"
    expected = platform + ":" + user
    source = SessionSource(Platform(platform), "bound-route", user_id=user)
    policy = LocalSessionPolicy("cli", "cli", str(tmp_path), None, (), "{}", "{}", "{}",
                                ignore_user_config=True)
    access, reads = Access(context()), []
    original = module.get_session_env
    def read(name, *args):
        reads.append(name)
        return original(name, *args)
    monkeypatch.setattr(module, "get_session_env", read)
    with policy_scope(policy) if platform == "local" else nullcontext():
        with bound(source):
            assert access.identity() == expected
            access.require(SimpleNamespace(owner=expected))
            monkeypatch.setenv("HERMES_SESSION_ACTOR_ID", planted)
            reads.clear()
            assert access.identity() == expected
            assert ("HERMES_SESSION_ACTOR_ID" in reads) is HAS_ACTOR
            access.require(SimpleNamespace(owner=expected))
            with pytest.raises(EnvironmentConnectionError):
                access.require(SimpleNamespace(owner="local" if platform == "local" else "telegram:owner"))


@actor_core
@pytest.mark.parametrize("route", ["", f"uid:{os.getuid()}", f"uid:{os.getuid() + 1}"])
@pytest.mark.parametrize("kind", ["policy", "legacy", "cron-empty", "cron"])
def test_empty_actor_host_rules_require_an_empty_route(tmp_path, route, kind):
    access, device = Access(context()), SimpleNamespace(owner="local")
    policy = LocalSessionPolicy("cli", "cli", str(tmp_path), None, (), "{}", "{}", "{}",
                                ignore_user_config=True)
    platform = "local" if kind == "policy" else ("cron" if kind == "cron" else "")
    params = dict(platform=platform, source="cli" if kind == "legacy" else "",
                  cron_session="1" if kind.startswith("cron") else "", actor_id="")
    def check():
        with policy_scope(policy) if kind in ("policy", "legacy") else nullcontext():
            tokens = set_session_vars(**params)
            try:
                assert values()["route"] == "" and values()["actor"] == ""
                assert access.identity() == "local"
                access.require(device)
                set_session_vars(**params, user_id=route)
                assert values()["route"] == route and values()["actor"] == ""
                if route:
                    assert access.identity() == ""
                    with pytest.raises(EnvironmentConnectionError):
                        access.require(device)
                else:
                    access.require(device)
            finally:
                clear_session_vars(tokens)
    Context().run(check)


@actor_core
def test_scoped_followup_actor_changes_and_clears_without_route_change():
    from gateway.session_context import scoped_turn_actor
    from gateway.session_state import TurnState
    access = Access(context())
    owner, follower_device = SimpleNamespace(owner="telegram:owner"), SimpleNamespace(owner="telegram:follower")
    with turn("owner", "owner") as opener:
        state = TurnState(event=opener)
        access.require(owner)
        follower = MessageEvent("queued follow-up", source=opener.source, user_id="follower")
        with scoped_turn_actor(follower, state):
            copied = copy_context()
            assert state.running_event() is follower
            assert copied.run(values) == dict(actor="follower", route="owner", platform="telegram")
            copied.run(access.require, follower_device)
            with pytest.raises(EnvironmentConnectionError):
                copied.run(access.require, owner)
            state.running_event().absorb_turn_input(opener)
            assert copied.run(values) == dict(actor="", route="owner", platform="telegram")
            assert copied.run(access.identity) == ""
            for device in (owner, follower_device):
                with pytest.raises(EnvironmentConnectionError):
                    copied.run(access.require, device)
        assert state.running_event() is opener
        assert access.identity() == "telegram:owner"
        access.require(owner)


def test_launch_session_environment_is_not_inherited():
    code = """
import json
import os
import conftest
import sys
sys.path.insert(0, str(conftest.ROOT))
from actor_context import values
from test_actor_identity import context
from dirtside.access import Access
print(json.dumps(dict(remaining=[n for n in os.environ if n.startswith("HERMES_SESSION_")
    or n == "HERMES_CRON_SESSION"], values=values(), sender=Access(context()).identity())))
"""
    env = dict(os.environ, HERMES_SESSION_ACTOR_ID="owner", HERMES_SESSION_USER_ID="owner",
               HERMES_SESSION_PLATFORM="telegram", HERMES_SESSION_SOURCE="telegram",
               HERMES_SESSION_TEST_POISON="planted", HERMES_CRON_SESSION="1")
    result = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == dict(remaining=[], values=dict(actor=None, route="", platform=""), sender="")


def test_actor_probe_matches_real_binder_without_its_own_gate():
    import dirtside.access as module
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner
    from gateway.session import build_session_context
    source = SessionSource(Platform.TELEGRAM, "probe-route", user_id="route-user")
    event = MessageEvent("different actor", source=source, user_id="actor-user")
    params = {"event": event} if "event" in inspect.signature(build_session_context).parameters else {}
    ctx = build_session_context(source, GatewayConfig(), **params)
    tokens = GatewayRunner._set_session_env(SimpleNamespace(adapters={}), ctx)
    try:
        actual = values()
        assert actual["route"] == "route-user" and actual["actor"] in (None, "actor-user")
        assert module._HAS_ACTOR is (actual["actor"] == "actor-user")
        assert Access(context()).identity() == "telegram:" + (actual["actor"] or actual["route"])
    finally:
        clear_session_vars(tokens)


def test_actor_probe_survives_an_unpublished_setter_moving():
    code = """
import importlib
import conftest
import sys
from unittest.mock import patch
sys.path.insert(0, str(conftest.ROOT))
import dirtside.access as module
from gateway import session_context
del session_context.set_session_vars
importlib.reload(module)
for error in (ImportError, ValueError, RuntimeError):
    with patch("importlib.util.find_spec", side_effect=error("unavailable")):
        assert importlib.reload(module)._HAS_ACTOR is False
print("ok")
"""
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
