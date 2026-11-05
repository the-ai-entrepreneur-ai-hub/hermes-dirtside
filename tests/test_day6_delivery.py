"""Recovery, independent feed capacity and replay regressions over signed HTTP."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from network_support import listening, mounted

from dirtside.agent import loop
from dirtside.agent.executor import run
from dirtside.model import CHUNK_BYTES, FEED_BLOCK_S, MAX_OUTPUT_BYTES, Policy
from dirtside.protocol import WireExec, sign, verify
from test_agent import config
from test_protocol import result_body
from test_registry import paired, request
from test_routes import API, headers


def poll(client, device, token, key, body):
    return client.post(API + "/device/poll", headers=headers(token), json=sign(key, "poll", device.id, body))


def test_dropped_dispatch_is_recovered_and_runs_once(tmp_path, monkeypatch):
    with mounted(tmp_path) as (app, reg, relay, module), TestClient(app) as client:
        monkeypatch.setattr(module.model, "POLL_HOLD_S", 0)
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device, command="printf once >> executions; printf done"))
        dropped = poll(client, device, token, key, {})
        assert dropped.status_code == 200 and dropped.json()["body"]["exec"]["id"] == handle.req.id
        delivered = poll(client, device, token, key, {"running": []})
        assert delivered.status_code == 200
        env = verify(module.relay_key.verify_key, delivered.json(), int(time.time()))
        req = module.wire.parse_exec(env.body["exec"])
        assert req.id == handle.req.id
        out, tail = run(req, Policy((), 120, MAX_OUTPUT_BYTES, 1),
                        lambda seq, data: relay.feed(req.id, seq, data))
        assert relay.accept_result(device.id, req.id, out, tail)
        assert handle.wait(0) == 0 and handle.stdout.read() == b"done"
        assert (tmp_path / "executions").read_text() == "once"
        assert "exec" not in poll(client, device, token, key, {"running": []}).json()["body"]


@pytest.mark.parametrize("acknowledged,fed,legacy", [(True, False, False), (False, True, False),
                                                  (False, False, True)])
def test_poll_does_not_requeue_known_execution(tmp_path, monkeypatch, acknowledged, fed, legacy):
    with mounted(tmp_path) as (app, reg, relay, module), TestClient(app) as client:
        monkeypatch.setattr(module.model, "POLL_HOLD_S", 0)
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device))
        assert poll(client, device, token, key, {}).status_code == 200
        if fed:
            assert relay.feed(handle.req.id, 0, b"started")
        body = {} if legacy else {"running": [handle.req.id] if acknowledged else []}
        response = poll(client, device, token, key, body)
        assert response.status_code == 200 and "exec" not in response.json()["body"]
        handle.kill()
        handle.stdout.close()


@pytest.mark.parametrize("body", [{"running": None}, {"running": "r_" + "01" * 12},
                                  {"running": [1]}, {"running": ["bad"]}, {"running": [], "other": []}])
def test_poll_running_list_is_exact(tmp_path, body):
    with mounted(tmp_path) as (app, reg, relay, _), TestClient(app) as client:
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device))
        assert poll(client, device, token, key, body).status_code == 400
        assert handle.state.value == "queued"
        handle.kill()
        handle.stdout.close()


@pytest.mark.parametrize("kind", ["chunk", "result"])
def test_saturated_poll_pool_cannot_block_feeds(tmp_path, monkeypatch, kind):
    with mounted(tmp_path) as (app, reg, relay, module), TestClient(app) as client:
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device))
        cancelled = threading.Event()
        barrier = threading.Barrier(module.POLL_POOL._max_workers + 1)
        def park():
            barrier.wait(timeout=5)
            return relay.next("parked-device", 10, cancelled)
        parked = [module.POLL_POOL.submit(park) for _ in range(module.POLL_POOL._max_workers)]
        barrier.wait(timeout=5)
        threads = []
        original = getattr(relay, "accept_" + kind)
        def accept(*args):
            threads.append(threading.current_thread().name)
            return original(*args)
        monkeypatch.setattr(relay, "accept_" + kind, accept)
        body = dict(id=handle.req.id, seq=0, data="eA==")
        if kind == "result":
            body = result_body() | body
        try:
            with ThreadPoolExecutor(1) as caller:
                future = caller.submit(client.post, API + "/device/" + kind, headers=headers(token),
                                       json=sign(key, kind, device.id, body))
                try:
                    start = time.monotonic()
                    response = future.result(timeout=1)
                    assert response.status_code == 200 and time.monotonic() - start < 1
                    assert threads[0].startswith("dirtside-feed")
                finally:
                    cancelled.set()
                    with relay._condition:
                        relay._condition.notify_all()
        finally:
            cancelled.set()
            for future in parked:
                future.result(timeout=2)
            handle.kill()
            handle.stdout.close()


def test_three_second_reader_does_not_retry_or_cancel(tmp_path, monkeypatch):
    with mounted(tmp_path) as (app, reg, relay, _), listening(app) as url:
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device))
        # Fill the OS-dependent pipe capacity so the next chunk must await the reader.
        prefilling = bytearray()
        while True:
            try:
                prefilling.extend(b"p" * os.write(handle._write_fd, b"p" * 4096))
            except BlockingIOError:
                break
        attempts, received = [], bytearray()
        original = relay.accept_chunk
        def accept(*args):
            attempts.append(args[1].seq)
            return original(*args)
        monkeypatch.setattr(relay, "accept_chunk", accept)
        def read():
            time.sleep(3)
            received.extend(handle.stdout.read())
        reader = threading.Thread(target=read)
        reader.start()
        cfg = replace(config(url), device_id=device.id, token=token, key=key,
                      relay_pubkey=module_key(reg), policy=Policy((), 30, MAX_OUTPUT_BYTES, 1))
        req = WireExec(handle.req.id, "output", f"head -c {CHUNK_BYTES} /dev/zero; sleep 0.3; printf tail",
                       False, 20, None, str(tmp_path))
        with httpx.Client(base_url=url + "/", headers=headers(token)) as client:
            agent = loop._Agent(cfg, client, threading.Event(), SimpleNamespace(write=lambda *a, **k: None))
            cancel = threading.Event()
            try:
                agent.execute(req, cancel)
                assert handle.wait(0) == 0 and not cancel.is_set()
                assert attempts == [0]
            finally:
                handle.kill()
                reader.join(5)
                agent.pool.shutdown(wait=True)
                handle.stdout.close()
        assert not reader.is_alive()
        assert received == prefilling + b"\0" * CHUNK_BYTES + b"tail"


def module_key(reg):
    from nacl.signing import SigningKey
    return SigningKey(reg.relay_seed).verify_key


@pytest.mark.parametrize("remaining", [None, 1, 8, 40])
def test_upload_phase_timeouts_follow_feed_bound(remaining):
    observed = []
    def respond(req):
        observed.append(req.extensions["timeout"])
        return httpx.Response(200)
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(respond)) as client:
        deadline = float("inf") if remaining is None else time.monotonic() + remaining
        assert loop.post_until_2xx(client, config(), "chunk", {}, threading.Event(), threading.Event(),
                                   lambda: None, deadline)
    bound = float("inf") if remaining is None else remaining
    for phase, expected in (("connect", 5), ("read", FEED_BLOCK_S + 5), ("write", 30)):
        assert observed[0][phase] == pytest.approx(min(bound, expected), abs=0.02)


def test_replayed_poll_cannot_claim_or_refresh_contact(tmp_path, monkeypatch):
    with mounted(tmp_path) as (app, reg, relay, module), TestClient(app) as client:
        monkeypatch.setattr(module.model, "POLL_HOLD_S", 0)
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        first, second = relay.submit(request(device)), relay.submit(request(device, n=2))
        envelope = sign(key, "poll", device.id, {})
        assert client.post(API + "/device/poll", headers=headers(token), json=envelope).status_code == 200
        seen = relay.last_seen[device.id]
        response = client.post(API + "/device/poll", headers=headers(token), json=envelope)
        try:
            assert response.status_code == 400
            assert relay.last_seen[device.id] == seen and second.state.value == "queued"
        finally:
            first.kill(), second.kill()
            first.stdout.close(), second.stdout.close()


def test_agent_signs_current_running_ids(tmp_path):
    cfg, stop, bodies = config(), threading.Event(), []
    def respond(req):
        env = verify(cfg.key.verify_key, json.loads(req.content), int(time.time()))
        bodies.append(env.body)
        stop.set()
        return httpx.Response(200, json=sign(cfg.key, "poll", "relay", {}))
    with httpx.Client(base_url=cfg.gateway_url, transport=httpx.MockTransport(respond)) as client:
        agent = loop._Agent(cfg, client, stop, SimpleNamespace(write=lambda *a, **k: None))
        rid = "r_" + "01" * 12
        agent.running[rid] = threading.Event()
        try:
            agent.poll()
            assert bodies == [{"running": [rid]}]
        finally:
            agent.pool.shutdown(wait=True)


def test_cancelled_poll_cannot_recover_current_execution(tmp_path):
    with mounted(tmp_path) as (_, reg, relay, _):
        device, _, _ = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device))
        try:
            assert relay.next(device.id, 0)[0] == handle.req
            cancelled = threading.Event()
            cancelled.set()
            assert relay.next(device.id, 0, cancelled, running=[]) == (None, [])
            assert handle.state.value == "running"
        finally:
            handle.kill()
            handle.stdout.close()
