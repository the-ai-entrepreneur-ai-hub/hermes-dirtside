"""Live state, bounded lossless pipe feed and terminal-transition contracts."""
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from dirtside.model import CHUNK_BYTES, FEED_BLOCK_S, Outcome, RequestState
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired, request

FINISHED = Outcome(RequestState.FINISHED, 0, 1, False, "")


def setup_relay(root):
    reg = Registry(root / "data.db")
    device, _, _ = paired(reg, root)
    relay = Relay(reg)
    relay.touch(device.id)
    return relay, device


def test_close_idempotent(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    barrier = threading.Barrier(2)

    def close():
        barrier.wait()
        return relay.close(handle.req.id, FINISHED)

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: close(), range(2))) == [False, True]
    assert handle.wait(0) == 0 and handle.stdout.read() == b""
    assert relay.registry.recent(1)[0].state is RequestState.FINISHED
    assert handle.req.id not in relay.handles
    assert not relay.close(handle.req.id, FINISHED)


def test_kill_unblocks_wait(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    started = threading.Event()

    def wait():
        started.set()
        return handle.wait()

    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(wait)
        assert started.wait(1)
        start = time.monotonic()
        handle.kill()
        assert result.result(timeout=0.05) == 130
        assert time.monotonic() - start < 0.05
    assert handle.stdout.read() == b""
    assert relay.next(device.id, 0) == (None, [handle.req.id])
    handle.kill()


def test_lost_covers_queued(tmp_path):
    relay, device = setup_relay(tmp_path)
    running = relay.submit(request(device, 1))
    queued = relay.submit(request(device, 2))
    assert relay.next(device.id, 0)[0] == running.req
    with relay._condition:
        relay.last_seen[device.id] = time.monotonic() - 51
    assert not relay.is_online(device.id)
    assert running.poll() == queued.wait(0.1) == 255
    assert running.state is queued.state is RequestState.LOST
    assert running.stdout.read() == queued.stdout.read() == b""


def test_feed_dedupe(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    with ThreadPoolExecutor(2) as pool:
        assert all(pool.map(lambda _: relay.feed(handle.req.id, 0, b"abc"), range(2)))
    assert relay.feed(handle.req.id, 1, b"def")
    assert relay.feed(handle.req.id, 0, b"not repeated")
    assert relay.tail(handle.req.id) == b"abcdef"
    relay.close(handle.req.id, FINISHED)
    assert handle.stdout.read() == b"abcdef"
    assert not relay.feed(handle.req.id, 2, b"late")


def test_late_result_410(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    assert relay.close(handle.req.id, FINISHED)
    assert not relay.close(handle.req.id, FINISHED)
    assert not relay.feed("unknown", 0, b"data")
    assert not relay.feed(handle.req.id, 0, b"late")


def test_revoke_cancels_running(tmp_path):
    relay, device = setup_relay(tmp_path)
    running = relay.submit(request(device, 1))
    queued = relay.submit(request(device, 2))
    relay.next(device.id, 0)
    relay.registry.revoke(device.name, int(time.time()))
    relay.revoke(device.id)
    assert running.wait(0.1) == queued.wait(0.1) == 130
    assert not relay.is_online(device.id)
    with pytest.raises(PermissionError):
        relay.next(device.id, 0)
    with pytest.raises(PermissionError):
        relay.touch(device.id)


def test_wait_timeout(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    with pytest.raises(subprocess.TimeoutExpired):
        handle.wait(0.01)
    assert handle.poll() is None
    handle.kill()


def test_dispatch_wakes_and_preserves_order(tmp_path):
    relay, device = setup_relay(tmp_path)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(relay.next, device.id, 1)
        first = relay.submit(request(device, 1))
        second = relay.submit(request(device, 2))
        assert pending.result(timeout=1)[0] == first.req
    assert relay.next(device.id, 0)[0] == second.req
    assert relay.next(device.id, 0.01) == (None, [])
    first.kill()
    second.kill()


def test_feed_never_drops(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    received = bytearray()

    def read():
        while data := os.read(handle.stdout.fileno(), 4096):
            received.extend(data)
            time.sleep(0.1)

    with ThreadPoolExecutor(1) as pool:
        reader = pool.submit(read)
        for seq in range(3):
            start = time.monotonic()
            assert relay.feed(handle.req.id, seq, bytes([seq]) * CHUNK_BYTES)
            assert time.monotonic() - start < FEED_BLOCK_S
        assert relay.tail(handle.req.id) == b"\x02" * 4096
        relay.close(handle.req.id, FINISHED)
        reader.result(timeout=8)
    assert received == b"".join(bytes([seq]) * CHUNK_BYTES for seq in range(3))
    assert len(received) == 196608


def test_stopped_reader_becomes_lost(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    start = time.monotonic()
    for seq in range(16):
        if not relay.feed(handle.req.id, seq, b"x" * CHUNK_BYTES):
            break
    else:
        raise AssertionError("pipe unexpectedly accepted a megabyte without a reader")
    assert handle.poll() == 255 and handle.state is RequestState.LOST
    assert handle.outcome.reason == "gateway stopped reading output"
    assert time.monotonic() - start < FEED_BLOCK_S + 0.3
    handle.stdout.read()


def test_cancel_during_feed(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    started = threading.Event()

    def feed():
        started.set()
        return [relay.feed(handle.req.id, seq, b"x" * CHUNK_BYTES) for seq in range(16)]

    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(feed)
        assert started.wait(1)
        time.sleep(0.05)
        start = time.monotonic()
        handle.kill()
        assert not all(result.result(timeout=1.1))
        assert time.monotonic() - start <= 1.05
    handle.stdout.read()


def test_nonterminal_close_rejected(tmp_path):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    with pytest.raises(ValueError):
        relay.close(handle.req.id, Outcome(RequestState.RUNNING, 0, 0, False, ""))
    assert handle.poll() is None
    handle.kill()


def test_feed_select_slice_bounds_cancellation(tmp_path, monkeypatch):
    relay, device = setup_relay(tmp_path)
    handle = relay.submit(request(device))
    slices = []

    def cancel_during_select(readers, writers, errors, timeout):
        slices.append(timeout)
        handle.kill()
        return [], [], []

    monkeypatch.setattr("dirtside.relay.select.select", cancel_during_select)
    try:
        assert not relay.feed(handle.req.id, 0, b"data")
        assert slices == [0.25]
        assert handle.wait(0) == 130
    finally:
        handle.kill()
        handle.stdout.close()
