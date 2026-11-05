"""One keep-alive client, signed long polls and bounded device execution."""
import base64
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import httpx
from ..protocol import ProtocolError, ReplayGuard, parse_poll, sign, verify
from .activity import Activity
from .executor import run

DEVICE_API = "api/plugins/dirtside/device/"

def post_until_2xx(client, cfg, kind, body, cancel, stop, shutdown, deadline=float("inf")):
    delay = 1.0
    while not (stop.is_set() or cancel.is_set()):
        if time.monotonic() >= deadline:
            return False
        try:
            response = client.post(DEVICE_API + kind, json=sign(cfg.key, kind, cfg.device_id, body),
                                   timeout=min(2, max(0.01, deadline - time.monotonic())))
            if response.status_code == 401:
                shutdown()
                return False
            if response.status_code == 410:
                cancel.set()
                return False
            response.raise_for_status()
            if 200 <= response.status_code < 300:
                return True
        except httpx.HTTPError:
            pass
        cancel.wait(min(delay, max(0, deadline - time.monotonic())))
        delay = min(30.0, delay * 2)
    return False

class _Agent:
    def __init__(self, cfg, client, stop, activity):
        self.cfg, self.client, self.stop, self.activity = cfg, client, stop, activity
        self.running, self.lock, self.guard = {}, threading.RLock(), ReplayGuard()
        self.pool = ThreadPoolExecutor(max_workers=cfg.policy.max_parallel, thread_name_prefix="dirtside-exec")

    def shutdown(self):
        self.stop.set()
        with self.lock:
            for cancel in self.running.values():
                cancel.set()

    def post(self, kind, body, cancel, deadline=float("inf")):
        return post_until_2xx(self.client, self.cfg, kind, body, cancel, self.stop, self.shutdown, deadline)

    def execute(self, req, cancel):
        try:
            deadline = time.monotonic() + min(req.timeout_s, self.cfg.policy.max_timeout_s)
            self.activity.write("started", id=req.id)
            def send(seq, data):
                return self.post("chunk", dict(id=req.id, seq=seq, data=base64.b64encode(data).decode()),
                                 cancel, deadline)
            out, tail = run(req, self.cfg.policy, send, cancel=cancel)
            if out.reason == "gateway no longer accepts output" and time.monotonic() >= deadline:
                out = replace(out, exit_code=124, reason="command timed out")
            body = dict(id=req.id, **(asdict(out) | {"state": out.state.value}))
            if tail:
                body.update(seq=tail.seq, data=base64.b64encode(tail.data).decode())
            self.post("result", body, cancel)
            self.activity.write("finished", id=req.id, exit_code=out.exit_code)
        except Exception as exc:
            self.activity.write("execution-error", id=req.id, error=type(exc).__name__)
            self.shutdown()
        finally:
            with self.lock:
                self.running.pop(req.id, None)

    def dispatch(self, wire):
        env = verify(self.cfg.relay_pubkey, wire, int(time.time()), self.guard)
        if env.kind != "poll" or env.sender != "relay":
            raise ProtocolError("unexpected relay identity or message kind")
        req, cancels = parse_poll(env.body)
        with self.lock:
            for rid in cancels:
                if event := self.running.get(rid):
                    event.set()
            if req is not None:
                if req.id in self.running:
                    raise ProtocolError("request is already running")
                self.running[req.id] = cancel = threading.Event()
                self.pool.submit(self.execute, req, cancel)
        self.activity.write("contact")

    def poll(self):
        delay = 1.0
        while not self.stop.is_set():
            try:
                response = self.client.post(DEVICE_API + "poll",
                                            json=sign(self.cfg.key, "poll", self.cfg.device_id, {}))
                if response.status_code == 401:
                    self.activity.write("revoked")
                    return
                response.raise_for_status()
                self.dispatch(response.json())
                delay = 1.0
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                self.activity.write("poll-error", error=type(exc).__name__)
                self.stop.wait(delay)
                delay = min(30.0, delay * 2)

def serve(cfg, *, stop=None):
    stop, activity = stop or threading.Event(), Activity()
    previous = {}
    with httpx.Client(base_url=cfg.gateway_url.rstrip("/") + "/",
                      headers={"Authorization": f"Bearer {cfg.token}"}, timeout=35) as client:
        agent = _Agent(cfg, client, stop, activity)
        def interrupted(signum, frame):
            agent.shutdown()
            raise KeyboardInterrupt
        if threading.current_thread() is threading.main_thread():
            previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            agent.poll()
        except KeyboardInterrupt:
            pass
        finally:
            agent.shutdown()
            agent.pool.shutdown(wait=True)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            activity.write("stopped")
            activity.close()
