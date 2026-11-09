"""Thin loopback transport; core still reads the ordinary pipe-backed handle."""
import base64
import calendar
import json
import os
import re
import struct
import subprocess
import threading
import time
from dataclasses import asdict
import httpx
from .environment import EnvironmentConnectionError, RemoteProcessHandle
from .model import CHUNK_BYTES, FEED_BLOCK_S, Outcome, RequestRow, RequestState

OWNER_MISSING = "Dirtside owner is not running; start the Hermes gateway or dashboard"

def process_started(pid):
    value = subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="], text=True, timeout=2,
                                    env={"PATH": os.defpath, "LC_ALL": "C", "TZ": "UTC"})
    return calendar.timegm(time.strptime(value.strip(), "%a %b %d %H:%M:%S %Y"))

def check_status(response):
    if response.is_success:
        return
    response.read()
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    detail = detail if isinstance(detail, str) else response.reason_phrase
    detail = "".join(c for c in detail if c.isprintable())[:200]
    raise EnvironmentConnectionError(f"Dirtside owner answered {response.status_code}: {detail}")

def retry_disabled(response, deadline):
    if response.status_code != 401 or time.monotonic() >= deadline:
        return False
    response.read()
    try:
        if response.json().get("detail") != "Dirtside token routes are disabled":
            return False
    except (ValueError, AttributeError):
        return False
    response.close()  # This exact pre-handler refusal has no execution or stream side effect.
    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    return True

def frames(response):
    pending, chunks = bytearray(), iter(response.iter_bytes())
    def take(size):
        while len(pending) < size:
            pending.extend(next(chunks))
        part = bytes(pending[:size])
        del pending[:size]
        return part
    while size := struct.unpack("!I", take(4))[0]:
        if size > CHUNK_BYTES:
            raise ValueError("oversized local frame")
        yield take(size)
    for part in chunks:
        if len(pending) + len(part) > CHUNK_BYTES:
            raise ValueError("oversized local outcome")
        pending.extend(part)
    data = json.loads(pending)
    yield Outcome(**(data | {"state": RequestState(data["state"])}))

class Client:
    def __init__(self, relay):
        self.relay, self.registry = relay, relay.registry
        self.http = httpx.Client(trust_env=False, timeout=2, follow_redirects=False)
        self.headers = {"Authorization": "Bearer " + self.registry.local_secret}
        self.handles, self._lock = {}, threading.Lock()

    def origin(self):
        try:
            with self.registry.path.with_name("owner.json").open("rb") as stream:
                data = json.loads(stream.read(4096))
            origin, pid = data["origin"], data["pid"]
            if type(pid) is not int or pid <= 0 or not re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\]):[0-9]{1,5}", origin):
                raise ValueError("invalid owner")
            if not 0 < int(origin.rpartition(":")[2]) <= 65535:
                raise ValueError("invalid owner port")
            os.kill(pid, 0)
            if data["started"] != process_started(pid):
                return None
            return origin + "/api/plugins/dirtside/local"
        except (FileNotFoundError, ProcessLookupError):
            return None
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
            raise EnvironmentConnectionError(OWNER_MISSING) from None

    def request(self, method, path, *, origin=None, **kwargs):
        deadline = time.monotonic() + 3
        try:
            while True:
                current = self.origin()
                if current is None or (origin is not None and origin != current):
                    raise EnvironmentConnectionError(OWNER_MISSING)
                response = self.http.request(method, current + path, headers=self.headers, **kwargs)
                if path == "/exec" and retry_disabled(response, deadline):
                    continue
                check_status(response)
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise EnvironmentConnectionError(OWNER_MISSING) from None

    def is_online(self, device_id):
        return any(d.id == device_id and online for d, online, _ in self.device_status())

    def device_status(self):
        devices = self.registry.devices()
        origin = self.origin()
        if origin is None:
            return [(d, False, None) for d in devices]
        rows = {d["id"]: d for d in self.request("GET", "/devices", origin=origin)}
        return [(d, rows[d.id]["online"], rows[d.id]["last_seen"]) for d in devices if d.id in rows]

    def recent(self, limit, session_key=None):
        origin = self.origin()
        if origin is None:
            return [(row, b"") for row in self.registry.recent(limit, session_key)]
        rows = self.request("GET", "/requests", origin=origin, params={"limit": limit} |
                            ({"session_key": session_key} if session_key is not None else {}))
        return [(RequestRow(**{k: RequestState(v) if k == "state" else v for k, v in d.items() if k != "tail"}),
                 base64.b64decode(d["tail"], validate=True)) for d in rows]

    def is_lost(self, device_id):
        return False  # Only the owner's relay decides device loss.

    def revoke(self, device_id):
        if origin := self.origin():
            self.request("POST", "/devices", origin=origin, json={"device_id": device_id})

    def kill(self, request_id):
        with self._lock:
            entry = self.handles.get(request_id)
        if entry is None:
            return
        handle, origin = entry
        try:
            cancelled = self.request("POST", "/kill", origin=origin, params={"id": request_id}, json={})["cancelled"]
        except EnvironmentConnectionError as exc:
            self.finish(handle, Outcome(RequestState.LOST, 255, 0, False, str(exc)))
            return
        if cancelled:
            self.finish(handle, Outcome(RequestState.CANCELLED, 130, 0, False, ""))

    def submit(self, req):
        origin = self.origin()
        if origin is None:
            raise EnvironmentConnectionError(OWNER_MISSING)
        self.request("POST", "/exec", origin=origin, json=asdict(req))
        handle = RemoteProcessHandle(self, req)
        with self._lock:
            self.handles[req.id] = handle, origin
        thread = threading.Thread(target=self.stream, args=(handle, origin, os.dup(handle._write_fd)), daemon=True)
        thread.start()
        return handle

    def stream(self, handle, origin, fd):
        outcome = Outcome(RequestState.LOST, 255, 0, False, OWNER_MISSING)
        deadline = time.monotonic() + 3
        try:
            while True:
                if self.origin() != origin:
                    raise EnvironmentConnectionError(OWNER_MISSING)
                with self.http.stream("GET", f"{origin}/stream", params={"id": handle.req.id},
                                      headers=self.headers, timeout=httpx.Timeout(2, read=None)) as response:
                    if retry_disabled(response, deadline):
                        continue
                    check_status(response)
                    outcome = self.copy_stream(handle, response, fd)
                break
        except EnvironmentConnectionError as exc:
            outcome = Outcome(RequestState.LOST, 255, 0, False, str(exc))
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, RuntimeError):
            pass  # Partial bytes remain in the pipe; the failure becomes the terminal reason.
        finally:
            os.close(fd)
            self.finish(handle, outcome)

    def copy_stream(self, handle, response, fd):
        for part in frames(response):
            if isinstance(part, Outcome):
                return part
            if not self.relay._write(handle, fd, part, time.monotonic() + FEED_BLOCK_S):
                return Outcome(RequestState.LOST, 255, 0, False, "gateway stopped reading output")
        raise ValueError("missing local outcome")

    def finish(self, handle, outcome):
        with self._lock:
            if handle._done.is_set():
                return
            handle.state, handle.outcome = outcome.state, outcome
            os.close(handle._write_fd)
            handle._returncode = outcome.exit_code
            handle._done.set()
            self.handles.pop(handle.req.id, None)
