"""Device configuration and real-HTTP agent conformance."""
import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
import httpx
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from nacl.signing import SigningKey
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from network_support import generic_poll_rejections, listening, mounted, until
from tools.interrupt import set_interrupt

from dirtside.agent.config import DeviceConfig, default_policy, device_path, gateway_url
from dirtside.agent.activity import Activity
from dirtside.agent.loop import _Agent, serve
from dirtside.environment import DirtsideEnvironment
from dirtside.protocol import ProtocolError, parse_result, sign, verify
from test_executor import alive, await_file
from test_network import group, revoke, stop_group


def config(url="http://127.0.0.1:1"):
    return DeviceConfig(url, "01" * 16, "private-token", SigningKey.generate(),
                        SigningKey.generate().verify_key, "device", default_policy())


def test_configuration_roundtrip(tmp_path):
    scope = set_hermes_home_override(tmp_path)
    try:
        cfg = config()
        cfg.save()
        path = device_path()
        assert path == tmp_path / "dirtside" / "device.json"
        assert path.stat().st_mode & 0o777 == 0o600
        loaded = DeviceConfig.load()
        assert loaded == cfg and bytes(loaded.key) == bytes(cfg.key)
        assert loaded.policy.deny_patterns[0].search("sudo id")
        assert set(json.loads(path.read_text())) == {
            "gateway_url", "device_id", "token", "key", "relay_pubkey", "name", "policy",
        }
        assert "private-token" not in repr(cfg) and bytes(cfg.key).hex() not in repr(cfg)
        path.chmod(0o644)
        with pytest.raises(ValueError, match="private"):
            DeviceConfig.load()
        cfg.save()
        assert DeviceConfig.load() == cfg and not list(path.parent.glob(".device-*"))
    finally:
        reset_hermes_home_override(scope)


@pytest.mark.parametrize("url", ["http://example.com", "ftp://localhost", "https://u:p@example.com",
                               "https://example.com/?token=x", "https://example.com/#secret", "https://",
                               "https://example.com:0", "https://example.com:no", "https://example.com:65536"])
def test_configuration_bad_url(url):
    with pytest.raises(ValueError):
        gateway_url(url)


@pytest.mark.parametrize("change", [
    {"key": "00"}, {"relay_pubkey": "11"}, {"device_id": "bad"}, {"name": "../bad"},
    {"token": ""}, {"policy": {"deny_patterns": [], "max_timeout_s": True,
                               "max_output_bytes": 1, "max_parallel": 1}},
    {"policy": {"deny_patterns": [], "max_timeout_s": 1, "max_output_bytes": 1, "max_parallel": 0}},
    {"policy": {"deny_patterns": ["["], "max_timeout_s": 1, "max_output_bytes": 1, "max_parallel": 1}},
])
def test_configuration_bad_values(tmp_path, change):
    path = tmp_path / "device.json"
    config().save(path)
    data = json.loads(path.read_text()) | change
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        DeviceConfig.load(path)


def test_configuration_refuses_symlink(tmp_path):
    target = tmp_path / "private.json"
    config().save(target)
    link = tmp_path / "device.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        DeviceConfig.load(link)
    assert os.stat(target).st_mode & 0o777 == 0o600


def test_loop_over_isolated_http(tmp_path):
    app, relay_key, received = FastAPI(), SigningKey.generate(), []
    cfg = replace(config(), relay_pubkey=relay_key.verify_key)
    dispatched = threading.Event()

    @app.post("/api/plugins/dirtside/device/poll")
    async def poll(request: Request):
        env = verify(cfg.key.verify_key, await request.json(), int(time.time()))
        assert env.kind == "poll" and env.sender == cfg.device_id
        if dispatched.is_set():
            while not received:
                await asyncio.sleep(0.01)
            return JSONResponse({"detail": "device revoked"}, status_code=401)
        dispatched.set()
        body = dict(id="r_" + "ab" * 12, command="pwd", script="pwd", login=False,
                    timeout_s=20, stdin=None, cwd=str(tmp_path))
        return sign(relay_key, "poll", "relay", {"exec": body})

    @app.post("/api/plugins/dirtside/device/result")
    async def result(request: Request):
        env = verify(cfg.key.verify_key, await request.json(), int(time.time()))
        received.append(parse_result(env.body))
        return {}

    with listening(app) as url:
        thread = threading.Thread(target=serve, args=(replace(cfg, gateway_url=url),), daemon=True)
        thread.start()
        until(lambda: received)
        thread.join(5)
        assert not thread.is_alive()
    out, tail = received[0]
    assert out.exit_code == 0 and tail.data.decode().strip() == str(tmp_path)


def test_agent_pinned_key_replay_and_duplicate_dispatch(tmp_path):
    scope = set_hermes_home_override(tmp_path)
    relay_key = SigningKey.generate()
    cfg = replace(config(), relay_pubkey=relay_key.verify_key)
    activity = Activity()
    with httpx.Client(base_url=cfg.gateway_url) as client:
        agent = _Agent(cfg, client, threading.Event(), activity)
        body = {"exec": dict(id="r_" + "cd" * 12, command="printf executed >> dispatch; sleep 60",
                             script="printf executed >> dispatch; sleep 60", login=False,
                             timeout_s=120, stdin=None, cwd=str(tmp_path))}
        try:
            invalid = [
                sign(SigningKey.generate(), "poll", "relay", body),
                sign(relay_key, "poll", "other", body),
                sign(relay_key, "exec", "relay", body),
                sign(relay_key, "poll", "relay", {"exec": {"id": "bad"}}),
            ]
            for wire in invalid:
                with pytest.raises(ProtocolError):
                    agent.dispatch(wire)
            assert not agent.running and not (tmp_path / "dispatch").exists()
            heartbeat = sign(relay_key, "poll", "relay", {})
            agent.dispatch(heartbeat)
            with pytest.raises(ProtocolError, match="replayed"):
                agent.dispatch(heartbeat)
            agent.dispatch(sign(relay_key, "poll", "relay", body))
            until(lambda: (tmp_path / "dispatch").exists())
            with pytest.raises(ProtocolError, match="already running"):
                agent.dispatch(sign(relay_key, "poll", "relay", body))
        finally:
            agent.shutdown()
            agent.pool.shutdown(wait=True)
            activity.close()
            reset_hermes_home_override(scope)
        assert (tmp_path / "dispatch").read_text() == "executed"


def test_full_pair_execute_cancel_revoke_path_with_thread_agent(tmp_path):
    from dirtside.cli import handle

    retried, stop = threading.Event(), threading.Event()
    with mounted(tmp_path) as (app, reg, relay, _), listening(generic_poll_rejections(app, retried)) as url:
        code = reg.mint("thread-device", int(time.time()))
        scope = set_hermes_home_override(tmp_path / "install")
        try:
            assert handle(SimpleNamespace(dirtside_action="pair", gateway_url=url,
                                          name="thread-device", code=code)) is None
            cfg = DeviceConfig.load()
        finally:
            reset_hermes_home_override(scope)
        device = reg.active_device(cfg.name)
        thread = threading.Thread(target=serve, args=(cfg,), kwargs={"stop": stop}, daemon=True)
        thread.start()
        try:
            until(lambda: relay.is_online(device.id))
            remote = DirtsideEnvironment(relay, device, "thread-chat", "default", "~", 120)
            assert remote.execute("pwd")["output"] == device.home + "\n"
            assert remote.execute(f"cd '{tmp_path}'")["returncode"] == 0
            assert remote.execute("pwd")["output"] == str(tmp_path) + "\n"
            assert remote.cwd == str(tmp_path)
            ids = []
            def execute():
                ids.append(threading.get_ident())
                try:
                    return remote.execute("echo $$ > thread-stop.pid; printf partial; sleep 60")
                finally:
                    set_interrupt(False)
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(execute)
                pid = int(await_file(tmp_path / "thread-stop.pid"))
                try:
                    until(lambda: any(b"partial" in relay.tail(rid) for rid in list(relay.handles)))
                    pids = group(pid)
                    start = time.monotonic()
                    set_interrupt(True, ids[0])
                    result = future.result(timeout=1)
                    assert result["returncode"] == 130 and "partial" in result["output"]
                    until(lambda: not any(alive(p) for p in pids), timeout=5)
                    assert time.monotonic() - start < 5
                finally:
                    stop_group(pid)
            revoke(url, device.name)
            assert retried.wait(5) and thread.is_alive()
            stop.set()
            thread.join(5)
            assert not thread.is_alive() and reg.credential_for(cfg.token, int(time.time())) is None
        finally:
            stop.set()
            reg.revoke(device.name, int(time.time()))
            relay.revoke(device.id)
            thread.join(5)
        assert not thread.is_alive()
