"""Client pipes stream before exit and bound an unread output consumer."""
import os
import select
import time
from contextlib import ExitStack
from dataclasses import replace
import pytest
from client_support import client_relay
from dirtside.model import FEED_BLOCK_S, RequestState
from test_environment import device_setup
from test_registry import request
from network_support import until

def test_client_pipe_delivers_partial_bytes_before_terminal(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with client_relay(relay) as worker, fake:
        req = replace(request(device), script="printf ready; while :; do sleep 1; done")
        handle = worker.connection().submit(req)
        try:
            assert select.select([handle.stdout], [], [], 3)[0]
            assert os.read(handle.stdout.fileno(), 5) == b"ready"
            assert handle.poll() is None
            handle.kill()
            assert handle.wait(3) == 130
            assert relay.registry.recent(1)[0].state is RequestState.CANCELLED
        finally:
            handle.kill()
            handle.stdout.close()

def test_unread_client_pipe_propagates_bounded_loss(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with client_relay(relay) as worker, fake:
        req = replace(request(device), script="while :; do head -c 65536 /dev/zero; done", timeout_s=60)
        handle = worker.connection().submit(req)
        started = time.monotonic()
        try:
            assert handle.wait(FEED_BLOCK_S + 5) == 124
            assert time.monotonic() - started < FEED_BLOCK_S + 5
            assert handle.outcome.reason == "gateway stopped reading output"
            until(lambda: not fake.running, timeout=5)
            assert relay.registry.recent(1)[0].state is RequestState.LOST
        finally:
            handle.kill()
            handle.stdout.close()

def test_kill_completes_an_unread_client_pipe_immediately(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    with client_relay(relay) as worker, fake:
        req = replace(request(device), script="while :; do head -c 65536 /dev/zero; done", timeout_s=60)
        handle = worker.connection().submit(req)
        try:
            until(lambda: len(relay.tail(req.id)) > 0)
            handle.kill()
            assert handle.wait(0.5) == 130
            assert handle.state is RequestState.CANCELLED
            until(lambda: not fake.running, timeout=5)
        finally:
            handle.kill()
            handle.stdout.close()

@pytest.mark.parametrize("state,code,reason,truncated", [
    (RequestState.REFUSED, 126, "command matches deny pattern", False),
    (RequestState.LOST, 124, "device stopped reporting", False),
    (RequestState.FINISHED, 124, "", False),
    (RequestState.FINISHED, 124, "command timed out; output capped at 1000 bytes on the device", True),
])
def test_client_outcomes_keep_reason_and_timeout_rendering(tmp_path, state, code, reason, truncated):
    from dirtside.environment import DirtsideEnvironment
    from dirtside.model import Outcome
    relay, device, fake = device_setup(tmp_path)
    with ExitStack() as stack:
        stack.enter_context(fake)
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
        # Submit a silent handle without dispatching it to the device.
        fake.stop.set()
        fake.thread.join(1)
        worker = stack.enter_context(client_relay(relay))
        handle = worker.connection().submit(request(device, n=222))
        until(lambda: not relay._streams)
        relay.feed(handle.req.id, 0, b"partial")
        relay.close(handle.req.id, Outcome(state, code, 1, truncated, reason))
        result = env._wait_for_process(handle, timeout=1)
        local = relay.submit(request(device, n=223))
        relay.feed(local.req.id, 0, b"partial")
        relay.close(local.req.id, Outcome(state, code, 1, truncated, reason))
        assert result == env._wait_for_process(local, timeout=1)
        assert handle.outcome == local.outcome
