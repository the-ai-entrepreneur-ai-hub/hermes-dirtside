"""Output validation leaves the dashboard loop responsive and every post bounded."""
import base64
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from dirtside.model import PANE_TAIL_BYTES
from dirtside.protocol import ProtocolError, canonical, sign
from test_day8_output import BODY_MAX, PART_MAX, chunk_api as chunk_api
from test_protocol import result_body
from test_registry import request as exec_request
from test_relay import FINISHED
from test_routes import API, headers

RESULT_BODY_MAX = BODY_MAX + 1024


def output_wire(kind, device, key, handle, data):
    body = dict(id=handle.req.id, seq=0, data=base64.b64encode(data).decode())
    if kind == "result":
        body = result_body() | body
    return canonical(sign(key, kind, device.id, body))


def test_maximum_result_and_body_are_accepted_byte_exactly(chunk_api):
    client, relay, module, device, token, key, handle = chunk_api
    data = bytes(range(256)) * (PART_MAX // 256)
    content = output_wire("result", device, key, handle, data)
    assert len(content) < RESULT_BODY_MAX
    content += b" " * (RESULT_BODY_MAX - len(content))
    with ThreadPoolExecutor(1) as pool:
        reader = pool.submit(handle.stdout.read)
        try:
            response = client.post(API + "/device/result", headers=headers(token), content=content)
            assert response.status_code == 200, response.text
            assert handle.wait(0) == 0
            assert module.RESULT_BODY_BYTES == RESULT_BODY_MAX
        finally:
            relay.close(handle.req.id, FINISHED)
        assert reader.result(2) == data


def test_oversized_signed_result_is_refused_without_output(chunk_api):
    client, relay, module, device, token, key, handle = chunk_api
    content = output_wire("result", device, key, handle, b"x" * (PART_MAX + 1))
    assert len(content) < RESULT_BODY_MAX
    with pytest.raises(ProtocolError, match="^output part too large$"):
        module.wire.parse_result(module.json.loads(content)["body"])
    response = client.post(API + "/device/result", headers=headers(token), content=content)
    assert response.status_code == 400 and response.json() == {"detail": "invalid message"}
    assert handle._last_seq == -1 and not relay.tail(handle.req.id)
    assert handle.req.id in relay.handles


@pytest.mark.parametrize("length", [None, "1", str(RESULT_BODY_MAX + 1)])
def test_result_body_bound_precedes_decode_and_ignores_content_length(chunk_api, monkeypatch, length):
    client, relay, module, _, token, _, handle = chunk_api
    def not_verified(*args):
        pytest.fail("an oversized body must be refused before verification")
    monkeypatch.setattr(module.wire, "verify", not_verified)
    auth = headers(token)
    if length is not None:
        auth["Content-Length"] = length
    response = client.post(API + "/device/result", headers=auth,
                           content=iter([b" " * RESULT_BODY_MAX, b" "]))
    assert response.status_code == 413 and response.json() == {"detail": "output part too large"}
    assert handle._last_seq == -1 and not relay.tail(handle.req.id)
    assert handle.req.id in relay.handles


@pytest.mark.parametrize("kind", ["chunk", "result"])
@pytest.mark.parametrize("phase", ["json", "verify", "parse"])
def test_maximum_output_validation_does_not_block_concurrent_poll(chunk_api, monkeypatch, kind, phase):
    client, relay, module, device, token, key, handle = chunk_api
    relay.next(device.id, 0)
    probe = relay.submit(exec_request(device, n=2))
    data = b"x" * PART_MAX
    content = output_wire(kind, device, key, handle, data)
    entered, release, threads = threading.Event(), threading.Event(), []
    target = module.json if phase == "json" else module.wire
    name = "loads" if phase == "json" else "verify" if phase == "verify" else f"parse_{kind}"
    original, loop_thread = getattr(target, name), client.portal.call(threading.get_ident)
    def held(*args, **kwargs):
        matching = len(args[0]) > PART_MAX if phase == "json" else args[1]["kind"] == kind if phase == "verify" else True
        if matching:
            threads.append(threading.get_ident())
            entered.set()
            assert release.wait(5), "output validation was not released"
        return original(*args, **kwargs)
    monkeypatch.setattr(target, name, held)
    with ThreadPoolExecutor(3) as pool:
        reader = pool.submit(handle.stdout.read)
        upload = pool.submit(client.post, API + f"/device/{kind}", headers=headers(token), content=content)
        try:
            assert entered.wait(2)
            poll = pool.submit(client.post, API + "/device/poll", headers=headers(token),
                               json=sign(key, "poll", device.id, {"running": [handle.req.id]}))
            response = poll.result(2)
            assert response.status_code == 200 and response.json()["body"]["exec"]["id"] == probe.req.id
            assert not upload.done() and threads and all(thread != loop_thread for thread in threads)
            release.set()
            assert upload.result(2).status_code == 200
            if kind == "chunk":
                assert relay.tail(handle.req.id) == data[-PANE_TAIL_BYTES:]
        finally:
            release.set()
            probe.kill()
            relay.close(handle.req.id, FINISHED)
        assert reader.result(2) == data


def test_overlapping_same_sequence_retry_is_accepted_once(chunk_api, monkeypatch):
    client, relay, _, device, token, key, handle = chunk_api
    data, calls = b"x" * PART_MAX, []
    content = [output_wire("chunk", device, key, handle, data) for _ in range(2)]
    entered, release = threading.Event(), threading.Event()
    original = relay.accept_chunk
    def held(*args):
        calls.append(threading.get_ident())
        if len(calls) == 2:
            entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(relay, "accept_chunk", held)
    with ThreadPoolExecutor(3) as pool:
        reader = pool.submit(handle.stdout.read)
        uploads = [pool.submit(client.post, API + "/device/chunk", headers=headers(token), content=body)
                   for body in content]
        try:
            assert entered.wait(2)
            release.set()
            assert [upload.result(2).status_code for upload in uploads] == [200, 200]
            assert relay.tail(handle.req.id) == data[-PANE_TAIL_BYTES:]
        finally:
            release.set()
            relay.close(handle.req.id, FINISHED)
        assert reader.result(2) == data
