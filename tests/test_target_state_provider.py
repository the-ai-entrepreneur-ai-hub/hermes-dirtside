"""Provider regressions at bootstrap, optional lookup and history eviction."""
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from gateway.session_context import clear_session_vars, set_session_vars
from tools.environments.base import EnvironmentConnectionError
from tools.terminal_tool import get_session_cwd, record_session_cwd
from tools.tool_result_storage import STORAGE_DIR, _resolve_storage_dir, maybe_persist_tool_result

from dirtside.environment import DirtsideEnvironment
from dirtside.provider import DirtsideProvider
from test_environment import device_setup


@contextmanager
def conversation(key):
    tokens = set_session_vars(session_key=key, cron_session="")
    try:
        yield
    finally:
        clear_session_vars(tokens)


@pytest.fixture
def server_facade(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    provider = DirtsideProvider(relay.registry, relay)
    with conversation("provider-correction"):
        env = provider.create_environment(cwd=str(tmp_path), timeout=120)
        try:
            yield env, provider, device, fake
        finally:
            env.cleanup()


def test_blocked_device_bootstrap_does_not_stall_another_conversation(server_facade, monkeypatch):
    env, provider, device, fake = server_facade
    started, release = threading.Event(), threading.Event()
    original = DirtsideEnvironment.init_session
    provider._registry.set_target("blocked-bootstrap", device.id)

    def bootstrap(delegate):
        started.set()
        assert release.wait(30), "bootstrap was never released"
        original(delegate)

    def device_command():
        with conversation("blocked-bootstrap"):
            blocked = provider.create_environment(cwd="~", timeout=120)
            try:
                return blocked.execute("printf device-ready")
            finally:
                blocked.cleanup()

    def server_command():
        with conversation("provider-correction"):
            with provider._lock:
                for index in range(1024):
                    provider._state(f"bootstrap-history-{index}", "~")
                assert "blocked-bootstrap" not in provider._states
            assert provider.default_cwd == "~"
            assert env.cwd == env._cwd
            return env.execute("printf server-ready")

    monkeypatch.setattr(DirtsideEnvironment, "init_session", bootstrap)
    with fake, ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(device_command)
        try:
            assert started.wait(10), "device never entered bootstrap"
            result = pool.submit(server_command).result(timeout=10)
            assert result["returncode"] == 0 and result["output"] == "server-ready"
            assert not pending.done() and not release.is_set()
        finally:
            release.set()
        result = pending.result(timeout=5)
        assert result["returncode"] == 0 and result["output"] == "device-ready"
        assert provider._states["blocked-bootstrap"]["identity"] == ("blocked-bootstrap", device)
        assert len(provider._states) == 1024


@pytest.mark.parametrize("unavailable", ["offline", "revoked"])
def test_optional_temp_lookup_is_safe_before_device_creation(server_facade, monkeypatch, unavailable):
    env, provider, device, _ = server_facade
    provider._registry.set_target("provider-correction", device.id)
    if unavailable == "revoked":
        provider._registry.revoke(device.name, 2_000_000_000)
    absent = (
        "env_type", "host_cwd", "host_cwd_mount", "wait_for_cleanup", "stop_idle", "exec_prefix",
        "agent_visible_cache_base", "_remote_home", "_remote_home_detected", "_sync_manager",
        "_container_id", "_hermes_sandbox_home", "config", "_session_scoped", "_bd_desktop_home",
        "_bd_chromium", "_bd_desktop_user",
    )

    def unexpected(*args):
        raise AssertionError("optional attribute lookup resolved the target")

    with monkeypatch.context() as patch:
        patch.setattr(provider._registry, "target", unexpected)
        method = getattr(env, "get_temp_dir", None)
        assert callable(method)
        for name in absent:
            assert getattr(env, name, None) is None
    with pytest.raises(EnvironmentConnectionError):
        method()
    assert _resolve_storage_dir(env) == STORAGE_DIR
    assert len(env._environments) == 1
    assert not provider._relay.handles and provider._registry.recent(10) == []


def test_oversized_result_with_offline_selection_falls_back_inline(server_facade):
    env, provider, device, _ = server_facade
    provider._registry.set_target("provider-correction", device.id)
    content = "non-terminal result\n" * 10_000
    result = maybe_persist_tool_result(content, "external_tool", "offline-spill", env, threshold=0)
    assert result.startswith("non-terminal result\n")
    assert "[Truncated: tool response was 200,000 chars." in result
    assert result.endswith("Full output could not be saved to sandbox.]")
    assert "<persisted-output>" not in result
    assert len(result) < len(content)
    assert len(env._environments) == 1


@pytest.mark.parametrize("target", ["server", "device"])
@pytest.mark.parametrize("switch_away", [False, True], ids=["same-target", "return-to-target"])
def test_live_cwd_survives_transition_history_eviction(server_facade, tmp_path, target, switch_away):
    env, provider, device, fake = server_facade
    selected = "server" if target == "server" else device.id
    other = device.id if target == "server" else "server"
    project = tmp_path / "live project"
    project.mkdir()
    with fake:
        provider._registry.set_target("provider-correction", selected)
        result = env.execute("cd " + shlex.quote(str(project)))
        assert result["returncode"] == 0 and env.cwd == str(project)
        record_session_cwd("provider-correction", str(project))
        if switch_away:
            provider._registry.set_target("provider-correction", other)
            env._current()
        for index in range(1024):
            provider._state(f"history-{index}", "~")
        assert "provider-correction" not in provider._states
        provider._registry.set_target("provider-correction", selected)
        assert env.cwd == str(project)
        assert get_session_cwd("provider-correction") == str(project)
        result = env.execute("pwd", cwd=get_session_cwd("provider-correction"))
        assert result["returncode"] == 0 and result["output"].strip() == str(project)
        assert len(provider._states) == 1024
