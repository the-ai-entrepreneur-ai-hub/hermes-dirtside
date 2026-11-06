"""Core environment adapter and pipe-backed remote process handle."""
import os
import secrets
import shlex
import subprocess
import threading
import time
from contextvars import ContextVar

from tools.environments.base import BaseEnvironment, EnvironmentConnectionError

from .model import ExecRequest, Outcome, RequestId, RequestState

_COMMAND = ContextVar("dirtside_command", default="")
_WAIT = ContextVar("dirtside_wait", default=(None, 0))

def _status_suffix(proc, timeout, code):
    out = proc.outcome if proc is not None else None
    if out is None or not out.reason:
        return "", False
    timed_out = (out.state, code, out.exit_code, out.reason.partition("; ")[0]) == (
        RequestState.FINISHED, 124, 124, "command timed out")
    reason = out.reason.partition("; ")[2] if timed_out else out.reason
    suffix = f"\n[Command timed out after {timeout}s]" if timed_out else ""
    return suffix + (f"\n[Dirtside: {reason}]" if reason else ""), timed_out

def require_online(device, relay):
    if not relay.connection().is_online(device.id):
        raise EnvironmentConnectionError(f"Dirtside: device '{device.name}' is offline. Nothing was run on the server.",
                                         retry_hint="Start hermes dirtside serve on it, or run /dirtside use server.")

class RemoteProcessHandle:
    def __init__(self, relay, req):
        read_fd, self._write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        os.set_blocking(self._write_fd, False)
        self._relay, self.req = relay, req
        self._done, self._returncode = threading.Event(), None
        self.state, self.outcome = RequestState.QUEUED, None
        self._last_seq, self._feeding = -1, False

    def poll(self):
        if self._returncode is None and self._relay.is_lost(self.req.device_id):
            self._relay.close(self.req.id, Outcome(RequestState.LOST, 124, 0, False, "device stopped reporting"))
        return self._returncode

    def wait(self, timeout=None):
        deadline = float("inf") if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(self.req.id, timeout)
            self._done.wait(min(1.0, remaining))
        return self._returncode

    def kill(self):
        self._relay.kill(self.req.id)

    @property
    def returncode(self):
        return self._returncode

class DirtsideEnvironment(BaseEnvironment):
    _stdin_mode = "payload"
    _persistent = True
    _passwordless_sudo_probe_supported = False

    def __init__(self, relay, device, session_key, task_id, cwd, timeout):
        self._relay, self._device = relay, device
        self._session_key, self._task_id = session_key, task_id
        super().__init__(cwd=device.home if cwd in ("", "~") else cwd, timeout=timeout)
        self.init_session()

    def get_temp_dir(self):
        return self._device.temp_dir

    def execute(self, command, cwd="", **kwargs):
        token = _COMMAND.set(command)
        try:
            return super().execute(command, cwd, **kwargs)
        finally:
            _COMMAND.reset(token)

    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None, cwd=None):
        require_online(self._device, self._relay)
        req = ExecRequest(RequestId("r_" + secrets.token_hex(12)), self._device.id,
                          self._session_key, self._task_id, _COMMAND.get(), cmd_string,
                          login, timeout, stdin_data, cwd or self.cwd)
        return self._relay.connection().submit(req)

    def _wait_for_process(self, proc, timeout=120, **kwargs):
        token = _WAIT.set((proc, timeout))
        try:
            return super()._wait_for_process(proc, timeout=timeout, **kwargs)
        finally:
            _WAIT.reset(token)

    def _finalize_wait_result(self, output, rendered, code):
        suffix, timed_out = _status_suffix(*_WAIT.get(), code)
        if suffix:
            rendered = output.render(suffix=suffix)
            if timed_out and output.total_chars == 0:
                rendered = rendered.lstrip()
        result = super()._finalize_wait_result(output, rendered, code)
        if timed_out:
            result["hermes_timed_out"] = True
        return result

    def cleanup(self):
        try:
            if self._relay.connection().is_online(self._device.id):
                path = shlex.quote(self._snapshot_path)
                proc = self._run_bash(f"rm -f -- {path} {path}.tmp.*", timeout=5, cwd=self._device.home)
                self._wait_for_process(proc, timeout=5)
        except Exception:
            pass  # Cleanup cannot prevent core from releasing an environment.
