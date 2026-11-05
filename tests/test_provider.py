"""Conversation target precedence and real local backend behavior."""
import os
import threading
import time
from pathlib import Path

import pytest
from gateway.session_context import clear_session_vars, set_session_vars
from tools.environments.base import EnvironmentConnectionError
from tools.environments.local import LocalEnvironment

from dirtside.environment import DirtsideEnvironment
from dirtside.model import OnDevice, Server
from dirtside.provider import DirtsideProvider, resolve_target, session_identity
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_environment import device_setup
from test_registry import paired


def test_provider_flags(tmp_path):
    registry = Registry(tmp_path / "data.db")
    provider = DirtsideProvider(registry, Relay(registry))
    assert provider.name == "dirtside" and provider.is_available()
    assert provider.is_remote is True and provider.is_container is False
    assert provider.skip_container_guards is False
    assert provider.default_cwd == "~"
    assert DirtsideEnvironment._persistent is True


@pytest.mark.parametrize("chosen,cron,default,online,expected", [
    (False, False, "server", False, Server),
    (False, True, "macbook", True, Server),
    (False, False, "macbook", True, OnDevice),
    (True, True, "server", True, OnDevice),
    (True, False, "spare", True, OnDevice),
    (True, False, "server", False, EnvironmentConnectionError),
    ("server", False, "macbook", False, Server),
])
def test_resolve_target_table(tmp_path, chosen, cron, default, online, expected):
    registry = Registry(tmp_path / "data.db")
    device, _, _ = paired(registry, tmp_path)
    spare, _, _ = paired(registry, tmp_path, "spare")
    relay = Relay(registry)
    if chosen:
        registry.set_target("chat", "server" if chosen == "server" else device.id)
    if online:
        relay.touch(device.id)
        relay.touch(spare.id)
    if expected is EnvironmentConnectionError:
        with pytest.raises(expected):
            resolve_target("chat", cron, default, registry, relay)
    else:
        target = resolve_target("chat", cron, default, registry, relay)
        assert isinstance(target, expected)
        if isinstance(target, OnDevice):
            assert target.device == device


def test_offline_fails_closed(tmp_path):
    relay, device, _ = device_setup(tmp_path)
    relay.registry.set_target("chat", device.id)
    tokens = set_session_vars(session_key="chat")
    snapshots = set(Path(os.environ["TERMINAL_TEMP_DIR"]).iterdir())
    try:
        provider = DirtsideProvider(relay.registry, relay)
        with pytest.raises(EnvironmentConnectionError, match="offline") as error:
            provider.create_environment(cwd=str(tmp_path), timeout=120)
        assert "Nothing was run on the server" in str(error.value) + str(error.value.retry_hint)
        assert set(Path(os.environ["TERMINAL_TEMP_DIR"]).iterdir()) == snapshots
        assert not relay.handles and relay.registry.recent(10) == []
    finally:
        clear_session_vars(tokens)


@pytest.mark.parametrize("key,identifier,expected", [("key", "id", "key"), ("", "id", "id"), ("", "", "")])
def test_identity_fallback(tmp_path, key, identifier, expected):
    tokens = set_session_vars(session_key=key, session_id=identifier)
    try:
        assert session_identity() == expected
    finally:
        clear_session_vars(tokens)


def test_identity_is_thread_scoped(tmp_path):
    seen = []
    barrier = threading.Barrier(2)

    def read(key):
        tokens = set_session_vars(session_key=key)
        try:
            barrier.wait()
            seen.append(session_identity())
        finally:
            clear_session_vars(tokens)

    threads = [threading.Thread(target=read, args=(key,)) for key in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(1)
    assert sorted(seen) == ["first", "second"]


def test_revoked_target_fails_closed(tmp_path):
    relay, device, _ = device_setup(tmp_path)
    relay.registry.set_target("chat", device.id)
    relay.registry.revoke(device.name, int(time.time()))
    with pytest.raises(EnvironmentConnectionError, match="no longer paired"):
        resolve_target("chat", False, "server", relay.registry, relay)
    assert isinstance(resolve_target("other", False, device.name, relay.registry, relay), Server)


def test_absent_identity_uses_only_default(tmp_path):
    relay, _, _ = device_setup(tmp_path)
    assert isinstance(resolve_target("", False, "server", relay.registry, relay), Server)
    with pytest.raises(ValueError):
        relay.registry.set_target("", "not-a-device")


def test_server_target_local(tmp_path):
    registry = Registry(tmp_path / "data.db")
    provider = DirtsideProvider(registry, Relay(registry))
    tokens = set_session_vars(session_key="server-chat")
    try:
        env = provider.create_environment(cwd=str(tmp_path), timeout=120)
        assert type(env._current()) is LocalEnvironment
        assert env.execute("pwd")["output"].strip() == str(tmp_path)
        destination = tmp_path / "project"
        destination.mkdir()
        assert env.execute(f"cd '{destination}'")["returncode"] == 0
        assert env.execute("pwd")["output"].strip() == str(destination)
        assert env.cwd == str(destination)
        env.cleanup()
        env = provider.create_environment(cwd="~", timeout=120)
        assert type(env._current()) is LocalEnvironment and os.path.isabs(env.cwd)
        assert env.execute("pwd")["output"].strip() == env.cwd
        env.cleanup()
    finally:
        clear_session_vars(tokens)
