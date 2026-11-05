"""Single-owner live request state and lossless pipe delivery."""
import os
import select
import threading
import time
from collections import defaultdict

from .environment import RemoteProcessHandle
from .model import FEED_BLOCK_S, LOST_GRACE_S, OFFLINE_AFTER_S, PANE_TAIL_BYTES, TERMINAL, Outcome, RequestState

class Relay:
    def __init__(self, registry):
        self.registry, self._condition = registry, threading.Condition()
        self.handles, self.last_seen, self.tails = {}, {}, {}
        self.cancels, self._revoked = defaultdict(set), set()

    def submit(self, req):
        self.registry.log(req)
        handle = RemoteProcessHandle(self, req)
        with self._condition:
            self.handles[req.id], self.tails[req.id] = handle, bytearray()
            revoked = req.device_id in self._revoked
            self._condition.notify_all()
        if revoked:
            self.kill(req.id)
        return handle

    def touch(self, device_id):
        with self._condition:
            if device_id in self._revoked:
                raise PermissionError("device revoked")
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

    def next(self, device_id, wait_s):
        deadline = time.monotonic() + wait_s
        with self._condition:
            while True:
                if device_id in self._revoked:
                    raise PermissionError("device revoked")
                req = next((h.req for h in self.handles.values()
                            if h.req.device_id == device_id and h.state is RequestState.QUEUED), None)
                cancels = list(self.cancels.pop(device_id, ()))
                if req is not None:
                    self.handles[req.id].state = RequestState.RUNNING
                remaining = deadline - time.monotonic()
                if req is not None or cancels or remaining <= 0:
                    return req, cancels
                self._condition.wait(remaining)

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
                if select.select([], [fd], [], min(1, remaining))[1]:
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
            self.close(request_id, Outcome(RequestState.LOST, 124, 0, False, "gateway stopped reading output"))
            return False
        try:
            with self._condition:
                if seq <= handle._last_seq:
                    return not handle._done.is_set()
            if not self._write(handle, fd, data, deadline):
                self.close(request_id, Outcome(RequestState.LOST, 124, 0, False, "gateway stopped reading output"))
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
            tail.extend(data)
            del tail[:-PANE_TAIL_BYTES]
            return True

    def close(self, request_id, outcome):
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
        self.close(request_id, Outcome(RequestState.CANCELLED, 130, 0, False, "command cancelled"))

    def revoke(self, device_id):
        with self._condition:
            self._revoked.add(device_id)
            self.last_seen.pop(device_id, None)
            ids = [rid for rid, handle in self.handles.items() if handle.req.device_id == device_id]
            self._condition.notify_all()
        for rid in ids:
            self.kill(rid)
