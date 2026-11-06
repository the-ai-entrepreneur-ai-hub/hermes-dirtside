"""A replacement owner cancels silent orphaned work through the next poll."""
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from core_rig import Rig
from dirtside.agent.loop import revoked, serve
from dirtside.model import POLL_HOLD_S, RequestState
from dirtside.protocol import sign, verify
from matrix_cases import gateway_restart
from network_support import listening, mounted
from test_network import setup_agent
from test_registry import paired, request
from test_relay import setup_relay
from test_routes import API, headers


def test_unknown_running_ids_cancel_in_same_poll_reply(tmp_path, monkeypatch):
    relay, device = setup_relay(tmp_path)
    rid = request(device).id
    def no_wait(*_):
        pytest.fail("an orphan must be cancelled in the same poll reply")
    monkeypatch.setattr(relay._condition, "wait", no_wait)
    assert relay.next(device.id, POLL_HOLD_S, running=[rid, rid]) == (None, [rid])
    assert relay.registry.recent(10) == []


def test_orphan_poll_never_rewrites_terminal_history(tmp_path, monkeypatch):
    relay, device = setup_relay(tmp_path)
    req = request(device)
    relay.registry.log(req)
    relay.registry.running(req.id)
    relay.registry.mark_stale_lost(200)
    before = relay.registry.recent(10)
    assert (before[0].state, before[0].exit_code, before[0].reason) == (
        RequestState.LOST, 255, "gateway restarted")
    def no_registry():
        pytest.fail("orphan cancellation must not access the registry")
    with monkeypatch.context() as patch:
        patch.setattr(relay.registry, "_tx", no_registry)
        assert relay.next(device.id, 0, running=[req.id]) == (None, [req.id])
    assert relay.registry.recent(10) == before


@pytest.mark.parametrize("claimed", [False, True])
def test_known_live_handle_is_not_an_orphan(tmp_path, claimed):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    orphan = request(device, 2).id
    try:
        if claimed:
            assert relay.next(device.id, 0)[0] == handle.req
        req, cancels = relay.next(device.id, 0, running=[handle.req.id, orphan])
        assert req == (None if claimed else handle.req)
        assert cancels == [orphan]
        assert handle.state is RequestState.RUNNING and handle.poll() is None
    finally:
        handle.kill()
        handle.stdout.close()


@pytest.mark.parametrize("report", [{}, {"running": None}, {"running": []}])
@pytest.mark.parametrize("explicit_cancel", [False, True])
def test_legacy_and_empty_polls_add_no_orphan_cancels(tmp_path, report, explicit_cancel):
    relay, device = setup_relay(tmp_path)
    req = request(device)
    relay.registry.log(req)
    relay.registry.mark_stale_lost(200)
    pending = request(device, 2).id
    if explicit_cancel:
        relay.cancels[device.id].add(pending)
    assert relay.next(device.id, 0, **report) == (None, [pending] if explicit_cancel else [])


def test_orphan_cancel_repeats_until_device_drops_id(tmp_path):
    relay, device = setup_relay(tmp_path)
    rid = request(device).id
    for _ in range(2):
        assert relay.next(device.id, 0, running=[rid]) == (None, [rid])
    assert relay.next(device.id, 0, running=[]) == (None, [])
    assert relay.next(device.id, 0) == (None, [])


@pytest.mark.parametrize("gated", [False, True])
def test_signed_poll_cancels_only_unknown_running_ids(tmp_path, monkeypatch, gated):
    with mounted(tmp_path, gated) as (app, reg, relay, module), TestClient(app) as client:
        monkeypatch.setattr(module.model, "POLL_HOLD_S", 0)
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        handle = relay.submit(request(device))
        orphan = request(device, 2).id
        try:
            relay.next(device.id, 0)
            response = client.post(API + "/device/poll", headers=headers(token),
                                   json=sign(key, "poll", device.id, {"running": [handle.req.id, orphan]}))
            assert response.status_code == 200
            env = verify(module.relay_key.verify_key, response.json(), int(time.time()))
            assert env.body == {"cancel": [orphan]}
            assert handle.state is RequestState.RUNNING
        finally:
            handle.kill()
            handle.stdout.close()


@pytest.mark.slow
def test_real_gateway_restart_stops_silent_work_before_deadline(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        detail = gateway_restart(rig)
        assert "old group stopped, pairing reused" in detail
        assert "silent sleep 600 timeout=600 stopped" in detail
        assert f"(<{POLL_HOLD_S + 10}s)" in detail
        assert not list((rig.device_home / "user").glob(".dirtside-matrix-*"))


@pytest.mark.parametrize("body,expected", [
    ({"error": "unauthenticated", "detail": "Unauthorized"}, True),
    ({"detail": "Unauthorized"}, False),
    ({"error": "proxy", "detail": "Unauthorized"}, False),
    ({"error": "unauthenticated", "detail": "Unauthorized", "extra": True}, False),
])
def test_core_credential_rejection_requires_exact_body(body, expected):
    assert revoked(httpx.Response(401, json=body)) is expected
    assert not revoked(httpx.Response(503, json=body))


def test_agent_stops_when_core_rejects_revoked_token_before_route(tmp_path):
    with mounted(tmp_path) as (app, reg, _, _), listening(app) as url:
        device, cfg = setup_agent(reg, tmp_path, url)
        reg.revoke(device.name, int(time.time()))
        response = httpx.post(url + API + "/device/poll", headers=headers(cfg.token),
                              json=sign(cfg.key, "poll", device.id, {"running": []}), trust_env=False)
        assert response.status_code == 401
        assert response.json() == {"error": "unauthenticated", "detail": "Unauthorized"}
        stop = threading.Event()
        thread = threading.Thread(target=serve, args=(cfg,), kwargs={"stop": stop}, daemon=True)
        thread.start()
        try:
            thread.join(5)
            assert not thread.is_alive() and stop.is_set()
        finally:
            stop.set()
            thread.join(5)
