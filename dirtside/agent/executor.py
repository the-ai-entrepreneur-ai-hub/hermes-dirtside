"""Execute a device script with bounded byte streaming and process-group cancellation."""
import os
import select
import shutil
import signal
import subprocess
import threading
import time
from contextlib import suppress
from ..model import CHUNK_BYTES, FLUSH_MS, PART_MAX, Outcome, RequestState, device_timeout_s
from ..protocol import Chunk
from .policy import evaluate
def _signal(proc, sig):
    with suppress(ProcessLookupError):
        try:
            os.killpg(proc.pid, sig)
            return True
        except PermissionError:
            # macOS reports EPERM when only the exited group leader remains.
            if proc.poll() is None:
                raise
def _stop(proc):
    _signal(proc, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while (proc.poll() is None or _signal(proc, 0)) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _signal(proc, 0):
        _signal(proc, signal.SIGKILL)
    proc.wait()
def _stdin(proc, data):
    with suppress(BrokenPipeError, OSError), proc.stdin:
        proc.stdin.write(data.encode("utf-8", "surrogateescape"))
class _Output:
    def __init__(self, req, policy, send):
        self.id, self.limit, self.send = req.id, policy.max_output_bytes, send
        self.pending, self.seq, self.total = bytearray(), 0, 0
        self.first, self.truncated, self.eof = 0.0, False, False
    def add(self, data):
        take = min(len(data), max(0, self.limit - self.total))
        self.truncated |= take < len(data)
        if not self.pending:
            self.first = time.monotonic()
        self.pending.extend(data[:take])
        self.total += take
    def flush(self, exited):
        due = not exited and time.monotonic() - self.first >= FLUSH_MS / 1000
        if self.pending and (len(self.pending) >= PART_MAX or due):
            data = bytes(self.pending[:PART_MAX])
            del self.pending[:PART_MAX]
            seq, self.seq = self.seq, self.seq + 1
            self.first = time.monotonic()
            return self.send(seq, data)
        return True

    def tail(self):
        return Chunk(self.id, self.seq, bytes(self.pending)) if self.pending else None
def _read(proc, output, idle):
    if output.eof:
        # EOF can precede exit; wait briefly rather than add a fixed command delay.
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=0.01)
        return 3
    wait = max(0, output.first + FLUSH_MS / 1000 - time.monotonic()) if output.pending and proc.poll() is None else 0.1
    if select.select([proc.stdout], [], [], min(0.1, wait))[0]:
        data = os.read(proc.stdout.fileno(), CHUNK_BYTES)
        output.eof = not data
        output.add(data)
        return 3 if output.eof else 0
    return idle + 1 if proc.poll() is not None else 0

def _drain(proc, req, policy, output, cancel):
    deadline, idle = time.monotonic() + device_timeout_s(req.timeout_s, policy), 0
    while idle < 3 or proc.poll() is None:
        expired = time.monotonic() >= deadline
        if cancel.is_set() or expired:
            if expired and proc.poll() is not None:
                break
            _stop(proc)
            return (124, "command timed out") if expired else (130, "command cancelled")
        idle = _read(proc, output, idle)
        if not output.flush(proc.poll() is not None):
            _stop(proc)
            return 130, "gateway no longer accepts output"
    return proc.wait(), ""
def run(req, policy, send, *, cancel=None):
    start = time.monotonic()
    if refused := evaluate(req.command, policy):
        return Outcome(RequestState.REFUSED, 126, 0, False, refused.reason), None
    if cancel is not None and cancel.is_set():
        return Outcome(RequestState.FINISHED, 130, 0, False, "command cancelled"), None
    output = _Output(req, policy, send)
    try:
        proc = subprocess.Popen([shutil.which("bash") or "bash", *(["-l"] if req.login else []), "-c", req.script],
                                cwd=req.cwd, start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE if req.stdin is not None else subprocess.DEVNULL)
    except OSError as exc:
        return Outcome(RequestState.FINISHED, 126, 0, False, str(exc)), None
    if req.stdin is not None:
        threading.Thread(target=_stdin, args=(proc, req.stdin), daemon=True).start()
    try:
        code, reason = _drain(proc, req, policy, output, cancel or threading.Event())
    except BaseException:
        _stop(proc)
        raise
    finally:
        proc.stdout.close()
    if output.truncated:
        reason = "; ".join(filter(None, (reason, f"output capped at {policy.max_output_bytes} bytes on the device")))
    return Outcome(RequestState.FINISHED, code, int((time.monotonic() - start) * 1000),
                   output.truncated, reason), output.tail()
