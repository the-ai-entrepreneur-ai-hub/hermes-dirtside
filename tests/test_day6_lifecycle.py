"""Terminal failure visibility and device/environment lifecycle regressions."""
import json
import plistlib
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fake_device import FakeDevice
from nacl.signing import SigningKey
from network_support import listening, subprocess_agent

from dirtside.agent import loop
from dirtside.cli import service_spec
from dirtside.environment import DirtsideEnvironment
from dirtside.model import MAX_OUTPUT_BYTES, Outcome, Policy, RequestState
from dirtside.protocol import sign
from dirtside.provider import ConversationEnvironment, DirtsideProvider
from test_agent import config
from test_environment import device_setup
from test_executor import alive, await_file
from test_registry import paired, request


@pytest.mark.parametrize("foreign", [{}, {"detail": "Unauthorized"}, {"detail": "device revoked", "error": "proxy"},
                                     {"detail": ["device revoked"]}, "proxy requires login"])
def test_foreign_poll_401_keeps_execution_alive_and_polls_again(tmp_path, foreign):
    relay_key, cfg, seen = SigningKey.generate(), config(), []
    cfg = replace(cfg, relay_pubkey=relay_key.verify_key)
    rid = "r_" + "ab" * 12
    def respond(req):
        assert req.url.path.endswith("/poll")
        seen.append(json.loads(req.content)["body"])
        if len(seen) == 1:
            body = dict(id=rid, command="sleep", script="echo $$ > pid; sleep 60; :",
                        login=False, timeout_s=120, stdin=None, cwd=str(tmp_path))
            return httpx.Response(200, json=sign(relay_key, "poll", "relay", {"exec": body}))
        pid = int(await_file(tmp_path / "pid"))
        assert alive(pid) and not agent.running[rid].is_set()
        if len(seen) == 2:
            return httpx.Response(401, json=foreign)
        return httpx.Response(401, json={"detail": "device revoked"})
    with httpx.Client(base_url=cfg.gateway_url, transport=httpx.MockTransport(respond)) as client:
        agent = loop._Agent(cfg, client, threading.Event(), SimpleNamespace(write=lambda *a, **k: None))
        try:
            agent.poll()
            assert len(seen) == 3
            assert seen[1:] == [{"running": [rid]}, {"running": [rid]}]
        finally:
            agent.shutdown()
            agent.pool.shutdown(wait=True)
        assert not alive(int((tmp_path / "pid").read_text()))


@pytest.mark.parametrize("kind", ["chunk", "result"])
def test_foreign_upload_401_retries_without_shutdown(kind):
    attempts, stopped, cancel = [], threading.Event(), threading.Event()
    def respond(req):
        attempts.append(json.loads(req.content))
        return httpx.Response(401, json={"detail": "Unauthorized"}) if len(attempts) == 1 else httpx.Response(200)
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(respond)) as client:
        def shutdown():
            stopped.set()
            cancel.set()
        assert loop.post_until_2xx(client, config(), kind, {}, cancel, stopped, shutdown)
    assert len(attempts) == 2 and attempts[0]["nonce"] != attempts[1]["nonce"]
    assert not stopped.is_set() and not cancel.is_set()


@pytest.mark.parametrize("detail", ["device revoked", "unknown device credential"])
def test_plugin_revocation_exits_subprocess_successfully(tmp_path, detail):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    app = FastAPI()
    @app.post("/api/plugins/dirtside/device/poll")
    async def revoked():
        return JSONResponse({"detail": detail}, status_code=401)
    with listening(app) as url, subprocess_agent(config(url), tmp_path / "install") as proc:
        assert proc.wait(timeout=5) == 0


def test_rendered_services_do_not_restart_successful_revoke(tmp_path):
    _, text, *_ = service_spec("Darwin", "/bin/hermes", tmp_path, tmp_path)
    unit = plistlib.loads(text.encode())
    assert unit["KeepAlive"] == {"SuccessfulExit": False}
    _, text, *_ = service_spec("Linux", "/bin/hermes", tmp_path, tmp_path)
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert fields["Restart"] == "on-failure"


def test_device_spawn_failure_reason_is_visible(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        env.cwd = str(tmp_path / "absent-on-device")
        result = env.execute("pwd")
        reason = relay.registry.recent(1)[0].reason
        assert result["returncode"] == 126 and "absent-on-device" in reason
        assert result["output"] == f"\n[Dirtside: {reason}]"


def test_lost_request_reason_is_visible_without_timeout_flag(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
    handle = relay.submit(request(device))
    with relay._condition:
        relay.last_seen[device.id] = time.monotonic() - 51
    result = env._wait_for_process(handle, timeout=30)
    assert result == {"returncode": 255, "output": "\n[Dirtside: device stopped reporting]"}


@pytest.mark.parametrize("state,code", [(RequestState.FINISHED, 126), (RequestState.CANCELLED, 130),
                                       (RequestState.REFUSED, 126), (RequestState.LOST, 255)])
def test_every_nonempty_terminal_reason_is_rendered_once(tmp_path, state, code):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
    handle = relay.submit(request(device))
    assert relay.feed(handle.req.id, 0, b"partial")
    assert relay.close(handle.req.id, Outcome(state, code, 0, False, "specific reason"))
    assert env._wait_for_process(handle, timeout=1) == {
        "returncode": code, "output": "partial\n[Dirtside: specific reason]"}


def test_device_policy_timeout_returns_before_requested_deadline(tmp_path):
    relay, device, fake = device_setup(tmp_path, Policy((), 2, MAX_OUTPUT_BYTES, 1))
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        start = time.monotonic()
        result = env.execute("echo $$ > pid; printf partial; sleep 30", timeout=30)
        elapsed = time.monotonic() - start
        assert elapsed < 5
        assert result["returncode"] == 124 and result["hermes_timed_out"] is True
        assert result["output"] == "partial\n[Command timed out after 30s]"
        assert not alive(int((tmp_path / "pid").read_text()))


def test_cleanup_removes_only_its_device_snapshot_and_temps(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        snapshot = Path(env._snapshot_path)
        assert snapshot.is_file()
        temporary = Path(str(snapshot) + ".tmp.123")
        temporary.write_text("export LEFTOVER=1\n")
        other = tmp_path / "hermes-snap-other.sh"
        other.write_text("keep")
        env.cwd = str(tmp_path / "removed-working-directory")
        env.cleanup()
        assert not snapshot.exists() and not temporary.exists()
        assert other.read_text() == "keep"
        row = relay.registry.recent(1)[0]
        assert row.exit_code == 0 and row.preview == ""


def test_cleanup_offline_and_submission_failures_are_harmless(tmp_path, monkeypatch):
    relay, device, fake = device_setup(tmp_path)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        def fail(*args, **kwargs):
            assert kwargs["timeout"] == 5
            raise RuntimeError("transport disappeared")
        monkeypatch.setattr(env, "_run_bash", fail)
        assert env.cleanup() is None
    before = len(relay.registry.recent(100))
    relay.last_seen.clear()
    assert env.cleanup() is None
    assert len(relay.registry.recent(100)) == before


def test_unknown_attribute_probes_do_not_read_registry(tmp_path, monkeypatch):
    relay, _, fake = device_setup(tmp_path)
    with fake:
        env = ConversationEnvironment(DirtsideProvider(relay.registry, relay), "chat",
                                      str(tmp_path), 120, "default")
        def unexpected(*args):
            raise AssertionError("plain attribute probe read the registry")
        monkeypatch.setattr(relay.registry, "target", unexpected)
        try:
            for name in ("nope", "_session_scoped", "host_cwd"):
                assert getattr(env, name, None) is None
        finally:
            env.cleanup()


def test_probe_without_last_delegate_is_attribute_error():
    env = ConversationEnvironment.__new__(ConversationEnvironment)
    assert getattr(env, "nope", None) is None
    with pytest.raises(AttributeError):
        getattr(env, "nope")


def test_repair_keeps_chosen_identity_and_executes_without_reselecting(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    reg = relay.registry
    reg.set_target("chosen-chat", device.id)
    provider = DirtsideProvider(reg, relay)
    with fake:
        env = ConversationEnvironment(provider, "chosen-chat", "~", 120, "default")
        assert env.execute("printf before")["output"] == "before"
    new_device, new_token, new_key = paired(reg, tmp_path, now=int(time.time()))
    assert new_device.id == device.id and reg.target("chosen-chat") == device.id
    assert new_device.pubkey != device.pubkey
    assert reg.credential_for(fake.token, int(time.time())) is None
    with FakeDevice(relay, new_device, new_token, new_key):
        assert env.execute("printf after")["output"] == "after"
        env.cleanup()
