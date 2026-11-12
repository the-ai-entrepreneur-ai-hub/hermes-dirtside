"""Worker replay crosses real loader windows without duplicate execution."""
import json
import os
import secrets
import shlex
import socket
import threading
import time

import pytest
from core_rig import Core, Rig, until

from dirtside.client import OWNER_MISSING, Client
from dirtside.environment import EnvironmentConnectionError, RemoteProcessHandle
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_owner_correction import recorded
from test_registry import paired, request


def call_inside_reload(tmp_path, position, stage):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        with Core(rig.core.home, env=rig.core.env, worker=True) as worker:
            worker.call("target", session="chat", name=rig.name)
            assert worker.terminal("printf before")["output"] == "before"
            marker = tmp_path / "executed"
            command = f"printf x >> {shlex.quote(str(marker))}; printf done"
            params = dict(action="work", stage=stage, name=rig.name, command=command,
                          request_id="r_" + secrets.token_hex(12), session="chat")
            result = None
            if stage == "stream":
                result = worker.submit("registration", **params)
                until(lambda: worker.call("registration", action="worker_ready"))
            rig.core.call("registration", action="arm", position=position)
            reload = rig.core.submit("registration", action="pause")
            try:
                until(lambda: rig.core.call("registration", action="ready"))
                started = time.monotonic()
                if stage == "stream":
                    worker.call("registration", action="worker_send")
                else:
                    result = worker.submit("registration", **params)
                rig.core.call("registration", action="release")
                assert reload.result(10)["enabled"]
                reply = result.result(12)
                elapsed = time.monotonic() - started
                assert reply["exit_code"] == 0 and reply["output"] == "done", reply
                assert marker.read_text() == "x"
                rows = [row for row in rig.core.http("GET", "/requests").json() if row["preview"] == command[:120]]
                assert len(rows) == 1
                return rows[0], rig.core.call("registration", action="finish"), params, elapsed
            finally:
                if not reload.done():
                    rig.core.call("registration", action="release")
                    reload.result(12)


@pytest.mark.parametrize("position", [1, 5, 9])
@pytest.mark.parametrize("stage", ["exec", "stream"])
def test_worker_call_inside_real_reload_is_replayed_once(tmp_path, position, stage):
    row, responses, params, _ = call_inside_reload(tmp_path, position, stage)
    assert row["id"] == params["request_id"]
    assert [stage, 401] in responses and [stage, 200] in responses, responses


@pytest.mark.parametrize("position", [1, 5, 9])
def test_worker_terminal_inside_real_reload_recovers_through_core_retry(tmp_path, position):
    _, responses, _, elapsed = call_inside_reload(tmp_path, position, "devices")
    assert ["devices", 401] in responses and ["devices", 200] in responses, responses
    assert ["exec", 401] not in responses and ["stream", 401] not in responses, responses
    assert elapsed >= 2, elapsed  # Core's first retry waits two seconds; a client replay would return sooner.


def stale_closed_owner(tmp_path, entry):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        with Core(rig.core.home, env=rig.core.env, worker=True) as worker:
            worker.call("target", session="chat", name=rig.name)
            assert worker.terminal("printf before")["output"] == "before"
            assert rig.core.call("registration", action="refuse")["local_origin"] is None
            rig.core.call("registration", action="arm")
            marker = tmp_path / "not-executed"
            started = time.monotonic()
            command = f"printf forbidden > {shlex.quote(str(marker))}"
            if entry == "exec":
                with pytest.raises(AssertionError, match="answered 401"):
                    worker.call("registration", action="work", stage="exec", name=rig.name,
                                command=command, request_id="r_" + secrets.token_hex(12))
            else:
                assert "answered 401" in str(worker.terminal(command))
            elapsed = time.monotonic() - started
            responses = rig.core.call("registration", action="finish")
            assert not marker.exists()
            print(json.dumps(dict(entry=entry, stale_owner_seconds=elapsed, attempts=len(responses))))
            return elapsed, responses


def test_worker_with_stale_closed_owner_stops_at_the_same_deadline(tmp_path):
    elapsed, responses = stale_closed_owner(tmp_path, "exec")
    assert 2 <= elapsed < 4.5
    assert 2 <= len(responses) <= 100 and all(row == ["exec", 401] for row in responses)


def test_worker_terminal_with_stale_closed_owner_ends_with_core_retries(tmp_path):
    elapsed, responses = stale_closed_owner(tmp_path, "terminal")
    assert 12 <= elapsed < 17
    assert responses == [["devices", 401]] * 4, responses


@pytest.mark.parametrize("status", [400, 403, 409, 410, 503])
def test_other_real_owner_refusals_are_not_replayed(tmp_path, status):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent()
        rig.core.call("registration", action="arm")
        message = rig.core.call("registration", action="reject", status=status, name=rig.name)
        assert f"answered {status}" in message
        path = "stream" if status == 410 else "exec"
        assert rig.core.call("registration", action="finish") == [[path, status], ["devices", 200]]


def test_dropped_connection_is_a_single_attempt(tmp_path):
    registry = Registry(tmp_path / "data.db")
    client = Client(Relay(registry))
    device, *_ = paired(registry, tmp_path)
    accepted = []
    try:
        with socket.create_server(("127.0.0.1", 0)) as server:
            server.settimeout(0.1)
            stop = threading.Event()
            def drop():
                while not stop.is_set():
                    try:
                        connection, _ = server.accept()
                    except OSError:
                        continue
                    accepted.append(1)
                    connection.close()
            thread = threading.Thread(target=drop, daemon=True)
            thread.start()
            recorded(registry, origin=f"http://127.0.0.1:{server.getsockname()[1]}")
            req = request(device)
            handle = RemoteProcessHandle(client, req)
            try:
                with pytest.raises(EnvironmentConnectionError, match="owner is not running"):
                    client.submit(req)
                assert len(accepted) == 1
                client.stream(handle, client.origin(), os.dup(handle._write_fd))
                assert len(accepted) == 2 and handle.outcome.reason == OWNER_MISSING
            finally:
                handle.stdout.close()
                stop.set()
                thread.join(2)
    finally:
        client.http.close()
