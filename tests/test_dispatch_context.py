"""A cached environment follows the current turn, not the first conversation."""
from contextlib import nullcontext

import pytest
from gateway.session_context import clear_session_vars, set_session_vars
from tools.environments.local import LocalEnvironment

from client_support import client_relay
from dirtside.environment import DirtsideEnvironment
from dirtside.provider import DirtsideProvider
from test_environment import device_setup


@pytest.mark.parametrize("client", [False, True], ids=["in-process", "client"])
def test_cached_environment_dispatches_each_conversations_target(tmp_path, client):
    relay, device, fake = device_setup(tmp_path)
    for key, target in (("A", device.id), ("B", "server"), ("C", device.id)):
        relay.registry.set_target(key, target)
    with (client_relay(relay) if client else nullcontext(relay)) as transport, fake:
        tokens = set_session_vars(session_key="A", cron_session="")
        env = DirtsideProvider(relay.registry, transport).create_environment(cwd=str(tmp_path), timeout=120)
        first = env._current()
        try:
            commands = [
                ("A", DirtsideEnvironment, "export DIRTSIDE_SCOPE=A; printf A", "A"),
                ("B", LocalEnvironment, "printf server", "server"),
                ("C", DirtsideEnvironment, "printf %s ${DIRTSIDE_SCOPE-unset}", "unset"),
                ("A", DirtsideEnvironment, "printf %s $DIRTSIDE_SCOPE", "A"),
            ]
            for key, kind, command, expected in commands:
                set_session_vars(session_key=key, cron_session="")
                assert isinstance(env._current(), kind)
                result = env.execute(command)
                assert result["returncode"] == 0 and result["output"] == expected
            rows = relay.registry.recent(50)
            assert {(r.session_key, r.preview) for r in rows if r.preview} == {
                (key, command) for key, kind, command, _ in commands if kind is DirtsideEnvironment
            }
            clear_session_vars(tokens)
            assert env._current() is first
        finally:
            clear_session_vars(tokens)
            env.cleanup()


@pytest.mark.parametrize("client", [False, True], ids=["in-process", "client"])
@pytest.mark.parametrize("initial_cron", [False, True])
def test_cached_environment_reads_cron_at_each_dispatch(tmp_path, client, initial_cron):
    relay, device, fake = device_setup(tmp_path)
    with (client_relay(relay) if client else nullcontext(relay)) as transport, fake:
        tokens = set_session_vars(session_key="cron-chat", cron_session="1" if initial_cron else "")
        env = DirtsideProvider(relay.registry, transport, device.name).create_environment(
            cwd=str(tmp_path), timeout=120)
        try:
            for cron in (initial_cron, not initial_cron, initial_cron):
                set_session_vars(session_key="cron-chat", cron_session="1" if cron else "")
                assert isinstance(env._current(), LocalEnvironment if cron else DirtsideEnvironment)
                assert env.execute("printf context")["output"] == "context"
        finally:
            clear_session_vars(tokens)
            env.cleanup()
