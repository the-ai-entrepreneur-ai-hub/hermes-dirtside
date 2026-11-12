"""Single-owner live request state and lossless pipe delivery."""
import os
import threading
import time
from collections import defaultdict
from dataclasses import replace

from .access import Access
from .environment import RemoteProcessHandle
from .model import FEED_BLOCK_S, LOST_GRACE_S, OFFLINE_AFTER_S, PANE_TAIL_BYTES, TERMINAL, Outcome, RequestState
from .readiness import wait_ready

class Relay:
    def __init__(self, registry):
        self.registry, self._condition = registry, threading.Condition()
        self.handles, self.last_seen, self.tails = {}, {}, {}
        self.cancels, self._revoked = defaultdict(set), set()
        self._paired_keys = {}
        self._client, self._owner_pid, self._streams = None, None, {}
        self.access = Access()
        self._routes_enabled, self._routes_reason = (lambda: True), (lambda: "")

    def connection(self):
        return self if self._routes_enabled() and (self._client is None or self._owner_pid == os.getpid()) else self._client

    def submit_local(self, req):
        handle = self.submit(req)
        timer = threading.Timer(FEED_BLOCK_S, self.abandon, (req.id,))
        timer.daemon = True
        with self._condition:
            self._streams[req.id] = handle, timer
        timer.start()
        return handle

    def take_stream(self, request_id):
        with self._condition:
            entry = self._streams.pop(request_id, None)
        if entry is not None:
            handle, timer = entry
            timer.cancel()
            return handle

    def abandon(self, request_id):
        handle = self.take_stream(request_id)
        if handle is not None:
            self.close(request_id, Outcome(RequestState.LOST, 255, 0, False, "gateway stopped reading output"))
            handle.stdout.close()

    def submit(self, req):
        self.access.require(self.registry.device_by_id(req.device_id), req.sender)
        self.registry.log(req)
        handle = RemoteProcessHandle(self, req)
        with self._condition:
            self.handles[req.id], self.tails[req.id] = handle, bytearray()
            revoked = req.device_id in self._revoked
            self._condition.notify_all()
        if revoked:
            self.kill(req.id)
        return handle

    def paired(self, device):
        with self._condition:
            self._paired_keys[device.id] = device.pubkey
            self._revoked.discard(device.id)
            self.last_seen.pop(device.id, None)
            self._condition.notify_all()

    def _allow_device(self, device_id, pubkey):
        if device_id in self._revoked or (pubkey is not None and self._paired_keys.get(device_id, pubkey) != pubkey):
            raise PermissionError("device revoked")

    def touch(self, device_id, pubkey=None):
        with self._condition:
            self._allow_device(device_id, pubkey)
            self.last_seen[device_id] = time.monotonic()

    def is_online(self, device_id):
        with self._condition:
            return self.last_seen.get(device_id, float("-inf")) >= time.monotonic() - OFFLINE_AFTER_S

    def is_lost(self, device_id):
        with self._condition:
            return self.last_seen.get(device_id, float("-inf")) < time.monotonic() - OFFLINE_AFTER_S - LOST_GRACE_S

    def tail(self, request_id):
        with self._condition:
            return bytes(self.tails.get(request_id, b""))

    def device_status(self):
        devices = self.registry.devices()
        with self._condition:
            seen = [(device, self.last_seen.get(device.id)) for device in devices]
        now, wall = time.monotonic(), time.time()
        return [(device, at is not None and now - at <= OFFLINE_AFTER_S,
                 wall - (now - at) if at is not None else None) for device, at in seen]

    def recent(self, limit, session_key=None):
        rows = self.registry.recent(limit, session_key)
        with self._condition:
            return [(replace(row, state=self.handles[row.id].state) if row.id in self.handles else row,
                     self.tail(row.id)) for row in rows]

    def _owns(self, device_id, request_id):
        with self._condition:
            handle = self.handles.get(request_id)
            return handle is not None and handle.req.device_id == device_id

    def accept_chunk(self, device_id, chunk):
        return self._owns(device_id, chunk.id) and self.feed(chunk.id, chunk.seq, chunk.data)

    def accept_result(self, device_id, request_id, outcome, tail):
        if not self._owns(device_id, request_id):
            return False
        if tail and not self.feed(tail.id, tail.seq, tail.data):
            return False
        return self.close(request_id, outcome)

    def _recover(self, device_id, running, cancelled):
        if running is None or (cancelled is not None and cancelled.is_set()):
            return  # Legacy and abandoned polls cannot prove a missing dispatch.
        running = set(running)
        for handle in self.handles.values():
            if (handle.req.device_id, handle.state.value, handle._last_seq, handle._feeding) == (
                    device_id, RequestState.RUNNING.value, -1, False) and handle.req.id not in running:
                handle.state = RequestState.QUEUED

    def next(self, device_id, wait_s, cancelled=None, running=None, pubkey=None):
        deadline = time.monotonic() + wait_s
        with self._condition:
            self._allow_device(device_id, pubkey)
            self._recover(device_id, running, cancelled)
            if running is not None:
                self.cancels[device_id].update(rid for rid in running if rid not in self.handles)
            while True:
                if not self._routes_enabled() or (cancelled is not None and cancelled.is_set()):
                    return None, []
                req = next((h.req for h in self.handles.values()
                            if h.req.device_id == device_id and h.state.value == RequestState.QUEUED.value), None)
                cancels = list(self.cancels.pop(device_id, ()))
                if req is not None:
                    self.handles[req.id].state = RequestState.RUNNING
                    self.registry.running(req.id)
                remaining = deadline - time.monotonic()
                if req is not None or cancels or remaining <= 0:
                    return req, cancels
                self._condition.wait(min(remaining, 0.1) if cancelled is not None else remaining)
                self._allow_device(device_id, pubkey)

    def _writer(self, handle, deadline):
        with self._condition:
            ready = self._condition.wait_for(lambda: not handle._feeding or handle._done.is_set(),
                                             max(0, deadline - time.monotonic()))
            if not ready or handle._done.is_set():
                return None
            handle._feeding = True
            return os.dup(handle._write_fd)

    def _write(self, handle, fd, data, deadline):
        view = memoryview(data)
        while view:
            if handle._done.is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                if wait_ready(fd, min(0.25, remaining), write=True):
                    view = view[os.write(fd, view):]
            except BlockingIOError:
                continue
            except OSError:
                return False
        return True

    def feed(self, request_id, seq, data):
        deadline = time.monotonic() + FEED_BLOCK_S
        with self._condition:
            handle = self.handles.get(request_id)
        if handle is None:
            return False
        fd = self._writer(handle, deadline)
        if fd is None:
            self.close(request_id, Outcome(RequestState.LOST, 255, 0, False, "gateway stopped reading output"))
            return False
        try:
            with self._condition:
                if seq <= handle._last_seq:
                    return not handle._done.is_set()
            if not self._write(handle, fd, data, deadline):
                self.close(request_id, Outcome(RequestState.LOST, 255, 0, False, "gateway stopped reading output"))
                return False
            return self._fed(handle, seq, data)
        finally:
            os.close(fd)
            with self._condition:
                handle._feeding = False
                self._condition.notify_all()

    def _fed(self, handle, seq, data):
        with self._condition:
            if handle._done.is_set():
                return False
            handle._last_seq = seq
            tail = self.tails[handle.req.id]
            del tail[:max(0, len(tail) + len(data) - PANE_TAIL_BYTES)]
            tail.extend(memoryview(data)[-PANE_TAIL_BYTES:])
            return True

    def close(self, request_id, outcome):
        outcome = replace(outcome, state=RequestState(outcome.state.value))
        if outcome.state not in TERMINAL:
            raise ValueError("outcome is not terminal")
        with self._condition:
            handle = self.handles.pop(request_id, None)
            if handle is None:
                return False
            handle.state, handle.outcome = outcome.state, outcome
            os.close(handle._write_fd)
            handle._returncode = outcome.exit_code
            handle._done.set()
            self.tails.pop(request_id, None)
            if outcome.state in {RequestState.CANCELLED, RequestState.LOST}:
                self.cancels[handle.req.device_id].add(request_id)
            self._condition.notify_all()
        self.registry.close(request_id, outcome, int(time.time()))
        return True

    def kill(self, request_id):
        # Core renders its own timeout/interrupt suffix for gateway-initiated kills.
        self.close(request_id, Outcome(RequestState.CANCELLED, 130, 0, False, ""))

    def revoke(self, device_id):
        with self._condition:
            self._revoked.add(device_id)
            self.last_seen.pop(device_id, None)
            ids = [rid for rid, handle in self.handles.items() if handle.req.device_id == device_id]
            self._condition.notify_all()
        for rid in ids:
            self.kill(rid)
