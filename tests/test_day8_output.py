"""Slow-link batching and exact output-size trust boundaries."""
import base64
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from network_support import mounted

from dirtside import model
from dirtside.agent import executor
from dirtside.agent.executor import _Output, _read
from dirtside.model import CHUNK_BYTES, FLUSH_MS, MAX_OUTPUT_BYTES, PANE_TAIL_BYTES, Policy
from dirtside.protocol import ProtocolError, canonical, sign
from test_registry import paired, request as exec_request
from test_relay import FINISHED, setup_relay
from test_routes import API, headers

PART_MAX = 2 << 20
BODY_MAX = 4 * ((PART_MAX + 2) // 3) + 1024
POLICY = Policy((), 900, MAX_OUTPUT_BYTES, 4)


def test_capped_flood_coalesces_at_most_32_ordered_parts(monkeypatch):
    clock, sent = [0.0], []
    block = bytes(range(256)) * (CHUNK_BYTES // 256)
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def send(seq, data):
        assert data == block * (len(data) // CHUNK_BYTES)
        sent.append((seq, len(data)))
        clock[0] += 0.7
        return True
    output = _Output(SimpleNamespace(id="flood"), POLICY, send)
    for _ in range(MAX_OUTPUT_BYTES // CHUNK_BYTES):
        output.add(block)
        clock[0] += 0.00001
        assert output.flush(False)
    output.add(b"over the unchanged cap")
    if tail := output.tail():
        sent.append((tail.seq, len(tail.data)))
    assert len(sent) <= (MAX_OUTPUT_BYTES + PART_MAX - 1) // PART_MAX
    assert [seq for seq, _ in sent] == list(range(len(sent)))
    assert sum(size for _, size in sent) == MAX_OUTPUT_BYTES
    assert all(0 < size <= PART_MAX for _, size in sent)
    assert output.truncated and model.PART_MAX == PART_MAX


def test_100_bytes_leave_by_flush_deadline_even_between_read_slices(monkeypatch):
    clock, sent, waits = [0.0], [], []
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    output = _Output(SimpleNamespace(id="interactive"), POLICY,
                     lambda seq, data: sent.append((clock[0], seq, data)) or True)
    output.add(b"x" * 100)
    clock[0] = (FLUSH_MS - 1) / 1000
    assert output.flush(False) and not sent
    def no_more_output(reader, timeout):
        waits.append(timeout)
        clock[0] += timeout
        return False
    monkeypatch.setattr(executor, "wait_ready", no_more_output)
    assert _read(SimpleNamespace(stdout=object(), poll=lambda: None), output, 0) == 0
    assert output.flush(False)
    assert waits == pytest.approx([0.001])
    assert sent == [(FLUSH_MS / 1000, 0, b"x" * 100)]


def test_exited_shell_retains_existing_idle_drain_slices(monkeypatch):
    clock, waits = [0.0], []
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    output = _Output(SimpleNamespace(id="grandchild"), POLICY, lambda *_: True)
    output.add(b"tail")
    clock[0] = 1.0
    def idle(reader, timeout):
        waits.append(timeout)
        return False
    monkeypatch.setattr(executor, "wait_ready", idle)
    assert _read(SimpleNamespace(stdout=object(), poll=lambda: 0), output, 0) == 1
    assert waits == [0.1] and output.tail().data == b"tail"


@pytest.fixture(params=[False, True], ids=["gate-off", "gate-on"])
def chunk_api(tmp_path, request):
    with mounted(tmp_path, gate=request.param) as (app, registry, relay, module):
        with TestClient(app) as client:
            device, token, key = paired(registry, tmp_path)
            handle = relay.submit(exec_request(device))
            try:
                yield client, relay, module, device, token, key, handle
            finally:
                handle.kill()
                handle.stdout.close()


def test_maximum_signed_part_and_body_are_accepted_byte_exactly(chunk_api):
    client, relay, module, device, token, key, handle = chunk_api
    data = bytes(range(256)) * (PART_MAX // 256)
    body = dict(id=handle.req.id, seq=0, data=base64.b64encode(data).decode())
    wire = sign(key, "chunk", device.id, body)
    assert wire["v"] == 1
    content = canonical(wire)
    assert len(content) < BODY_MAX
    content += b" " * (BODY_MAX - len(content))
    with ThreadPoolExecutor(1) as pool:
        reader = pool.submit(handle.stdout.read)
        try:
            response = client.post(API + "/device/chunk", headers=headers(token), content=content)
            assert response.status_code == 200, response.text
            assert relay.tail(handle.req.id) == data[-PANE_TAIL_BYTES:]
            assert module.CHUNK_BODY_BYTES == BODY_MAX
        finally:
            relay.close(handle.req.id, FINISHED)
        assert reader.result(2) == data


def test_oversized_signed_part_preserves_error_and_fails_closed(chunk_api):
    client, relay, module, device, token, key, handle = chunk_api
    body = dict(id=handle.req.id, seq=0, data=base64.b64encode(b"x" * (PART_MAX + 1)).decode())
    with pytest.raises(ProtocolError, match="^output part too large$"):
        module.wire.parse_chunk(body)
    wire = sign(key, "chunk", device.id, body)
    assert len(canonical(wire)) < BODY_MAX
    response = client.post(API + "/device/chunk", headers=headers(token), json=wire)
    assert response.status_code == 400 and response.json() == {"detail": "invalid message"}
    assert handle._last_seq == -1 and not relay.tail(handle.req.id)
    assert handle.req.id in relay.handles


@pytest.mark.parametrize("length", [None, "1", str(BODY_MAX + 1)])
def test_chunk_body_bound_counts_stream_bytes_not_content_length(chunk_api, length):
    client, relay, _, _, token, _, handle = chunk_api
    auth = headers(token)
    if length is not None:
        auth["Content-Length"] = length
    response = client.post(API + "/device/chunk", headers=auth,
                           content=iter([b" " * BODY_MAX, b" "]))
    assert response.status_code == 413
    assert response.json() == {"detail": "output part too large"}
    assert handle._last_seq == -1 and not relay.tail(handle.req.id)


def test_pane_tail_never_copies_a_whole_large_part(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(exec_request(device))
    class BoundedTail(bytearray):
        def extend(self, data):
            assert len(self) + len(data) <= PANE_TAIL_BYTES
            super().extend(data)
    relay.tails[handle.req.id] = BoundedTail(b"prefix")
    try:
        assert relay._fed(handle, 0, b"x" * PART_MAX)
        assert relay.tail(handle.req.id) == b"x" * PANE_TAIL_BYTES
        assert relay._fed(handle, 1, b"next")
        assert relay.tail(handle.req.id) == b"x" * (PANE_TAIL_BYTES - 4) + b"next"
    finally:
        handle.kill()
        handle.stdout.close()
