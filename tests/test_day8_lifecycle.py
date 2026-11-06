"""Claim history is durable before output, and never rewritten per chunk."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from network_support import DESKTOP_TOKEN, mounted

from dirtside.local import PREFIX
from dirtside.model import RequestState
from dirtside.protocol import sign
from test_registry import paired, request
from test_relay import setup_relay
from test_routes import API, headers


def test_claim_records_running_once_and_chunks_never_write_history(tmp_path):
    relay, device = setup_relay(tmp_path)
    first, queued = (relay.submit(request(device, n=n)) for n in (1, 2))
    with sqlite3.connect(relay.registry.path) as conn:
        conn.executescript("""
            CREATE TABLE claims (id TEXT);
            CREATE TRIGGER record_claim AFTER UPDATE OF state ON requests
            WHEN NEW.state='running' BEGIN INSERT INTO claims VALUES(NEW.id); END;
        """)
    try:
        assert relay.next(device.id, 0)[0] == first.req
        rows = {r.id: r for r in relay.registry.recent(2)}
        assert rows[first.req.id].state is RequestState.RUNNING
        assert rows[queued.req.id].state is RequestState.QUEUED
        assert rows[first.req.id].finished_at is rows[first.req.id].exit_code is rows[first.req.id].reason is None
        assert first._last_seq == -1 and not relay.tail(first.req.id)
        # A recovered, unstarted claim must not produce a second running write.
        assert relay.next(device.id, 0, running=[])[0] == first.req
        assert relay.feed(first.req.id, 0, b"one") and relay.feed(first.req.id, 1, b"two")
        with sqlite3.connect(relay.registry.path) as conn:
            assert conn.execute("SELECT id FROM claims").fetchall() == [(first.req.id,)]
            assert dict(conn.execute("SELECT id,state FROM requests")) == {
                first.req.id: "running", queued.req.id: "queued"}
    finally:
        first.kill()
        queued.kill()
        first.stdout.close()
        queued.stdout.close()


@pytest.mark.parametrize("gate", [False, True])
def test_silent_claim_visible_in_pane_local_and_stored_history(tmp_path, monkeypatch, gate):
    with mounted(tmp_path, gate=gate) as (app, registry, relay, module):
        device, token, key = paired(registry, tmp_path, now=int(time.time()))
        monkeypatch.setattr(module.model, "POLL_HOLD_S", 0)
        with TestClient(app, client=("127.0.0.1", 1234)) as client:
            assert client.post(API + "/device/poll", headers=headers(token),
                               json=sign(key, "poll", device.id, {})).status_code == 200
            first, queued = (relay.submit(request(device, n=n)) for n in (1, 2))
            try:
                assert relay.next(device.id, 0)[0] == first.req
                for path, token in ((API + "/requests", DESKTOP_TOKEN), (PREFIX + "/requests", registry.local_secret)):
                    response = client.get(path, headers=headers(token))
                    assert response.status_code == 200
                    rows = response.json()
                    assert {r["id"]: r["state"] for r in rows} == {
                        first.req.id: "running", queued.req.id: "queued"}
                    assert all(r["tail"] == "" and r["finished_at"] is None for r in rows)
                assert {r.id: r.state for r in registry.recent(2)} == {
                    first.req.id: RequestState.RUNNING, queued.req.id: RequestState.QUEUED}
            finally:
                first.kill()
                queued.kill()
                first.stdout.close()
                queued.stdout.close()
