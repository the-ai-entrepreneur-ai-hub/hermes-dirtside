"""Discovery-mounted routes behind the complete core dashboard auth stack."""
import base64
import time

from core_rig import Rig, until
import httpx
from nacl.signing import SigningKey
import pytest

from dirtside.protocol import sign


def device_post(rig, path, kind, body):
    cfg = rig.config
    return rig.core.http("POST", "/device/" + path, authenticated=False,
                         headers={"Authorization": "Bearer " + cfg["token"]},
                         json=sign(SigningKey(bytes.fromhex(cfg["key"])), kind, cfg["device_id"], body))


def test_all_device_paths_use_device_auth_without_dashboard_session(tmp_path):
    with Rig(tmp_path) as rig:
        assert rig.core.info["gate"]
        for path in ("pair", "poll", "chunk", "result"):
            response = rig.core.http("POST", "/device/" + path, authenticated=False,
                                     headers={"Authorization": "Bearer unknown"}, json={})
            assert response.status_code == 401, (path, response.text)
        # Pair uses the pending device's bearer, which rotates to the paired bearer.
        rig.pair()
        assert not rig.agent
        request_id = rig.core.call("queue", name=rig.name, session="routes")["id"]
        response = device_post(rig, "poll", "poll", {})
        assert response.status_code == 200
        assert response.json()["body"]["exec"]["id"] == request_id
        body = dict(id=request_id, seq=0, data=base64.b64encode(b"route-output").decode())
        assert device_post(rig, "chunk", "chunk", body).status_code == 200
        outcome = dict(id=request_id, state="finished", exit_code=0, duration_ms=1,
                       truncated=False, reason="")
        assert device_post(rig, "result", "result", outcome).status_code == 200
        assert device_post(rig, "result", "result", outcome).status_code == 410
        for path in ("pair", "poll", "chunk", "result"):
            response = rig.core.http("POST", "/device/" + path, json={})
            assert response.status_code == 401  # A dashboard session is not a device credential.
        row = rig.core.http("GET", "/requests?session_key=routes").json()[0]
        assert row["id"] == request_id and row["state"] == "finished" and row["exit_code"] == 0


def test_all_desktop_operations_require_a_dashboard_session(tmp_path):
    with Rig(tmp_path) as rig:
        rig.pair()
        operations = [
            ("GET", "/devices", None), ("GET", "/sessions/chat/target", None),
            ("PUT", "/sessions/chat/target", {"target": rig.name}), ("GET", "/requests", None),
            ("POST", "/pairing", {"name": "other"}), ("POST", f"/devices/{rig.name}/revoke", None),
        ]
        for method, path, body in operations:
            for headers in ({}, {"Authorization": "Bearer " + rig.config["token"]}):
                response = rig.core.http(method, path, authenticated=False, headers=headers, json=body)
                assert response.status_code == 401, (method, path, response.text)
            response = rig.core.http(method, path, json=body)
            assert response.status_code == 200, (method, path, response.text)


def test_pane_shapes_and_live_tail_after_real_tool_dispatch(tmp_path):
    with Rig(tmp_path) as rig:
        rig.pair().start_agent().choose()
        core = rig.core
        response = core.http("PUT", "/sessions/chat/target", json={"target": rig.name})
        assert response.json() == {"target": rig.name}
        assert core.http("GET", "/sessions/chat/target").json() == {"target": rig.name}
        future = core.submit("terminal", session="chat", args={"command": "printf live-pane; sleep 2; printf done"})
        def live():
            rows = core.http("GET", "/requests?session_key=chat").json()
            return next((row for row in rows if row["state"] == "running" and "live-pane" in row["tail"]), None)
        row = until(live)
        assert set(row) == {"id", "device_id", "session_key", "task_id", "state", "preview",
                            "created_at", "finished_at", "exit_code", "reason", "tail"}
        assert row["preview"] == "printf live-pane; sleep 2; printf done"
        assert row["finished_at"] is None and row["exit_code"] is None
        devices = core.http("GET", "/devices").json()
        assert len(devices) == 1
        assert set(devices[0]) == {"id", "name", "online", "os", "home", "last_seen"}
        assert devices[0]["online"] and devices[0]["name"] == rig.name
        assert devices[0]["last_seen"] > 0 and devices[0]["home"] == rig.device_env["HOME"]
        assert future.result(8)["output"] == "live-panedone"
        done = next(r for r in core.http("GET", "/requests").json() if r["id"] == row["id"])
        assert done["state"] == "finished" and done["exit_code"] == 0
        assert done["finished_at"] >= done["created_at"]
        assert done["tail"] == ""  # A11 keeps only live tails, not completed output.


@pytest.mark.slow
def test_disconnected_poll_cannot_claim_work_after_device_restart(tmp_path):
    with Rig(tmp_path) as rig:
        rig.pair()
        cfg = rig.config
        envelope = sign(SigningKey(bytes.fromhex(cfg["key"])), "poll", cfg["device_id"], {})
        with httpx.Client(timeout=0.2, trust_env=False) as old_connection:
            with pytest.raises(httpx.ReadTimeout):
                old_connection.post(rig.core.url + "/api/plugins/dirtside/device/poll", json=envelope,
                                    headers={"Authorization": "Bearer " + cfg["token"]})
        time.sleep(0.3)  # Let the gateway observe the real transport disconnect.
        request_id = rig.core.call("queue", name=rig.name, session="restarted")["id"]
        rig.start_agent()
        def completed():
            return next((r for r in rig.core.http("GET", "/requests").json()
                         if r["id"] == request_id and r["state"] == "finished"), None)
        assert until(completed, timeout=8)["exit_code"] == 0
