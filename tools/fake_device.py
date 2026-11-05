"""Signed in-process device for transport-independent integration tests."""
import base64
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from nacl.signing import SigningKey, VerifyKey
from dirtside.agent.executor import run
from dirtside.model import MAX_OUTPUT_BYTES, Policy
from dirtside.protocol import ProtocolError, ReplayGuard, WireExec, parse_chunk, parse_poll, parse_result, sign, verify
class FakeDevice:
    def __init__(self, relay, device, token, key, policy=None):
        self.relay, self.device, self.token, self.key = relay, device, token, key
        self.policy = policy or Policy((), 900, MAX_OUTPUT_BYTES, 4)
        self.relay_key = SigningKey(relay.registry.relay_seed)
        self.guard, self.stop, self.lock = ReplayGuard(), threading.Event(), threading.Lock()
        self.running, self.futures, self.posts, self.errors = {}, [], [], []
        self.pool = ThreadPoolExecutor(max_workers=self.policy.max_parallel)
        self.thread = threading.Thread(target=self._loop, daemon=True)
    def _accept(self, wire):
        credential = self.relay.registry.credential_for(self.token, int(time.time()))
        if credential != self.device:
            raise PermissionError("device bearer rejected")
        env = verify(VerifyKey(credential.pubkey), wire, int(time.time()))
        if env.sender != credential.id:
            raise ProtocolError("device sender mismatch")
        self.relay.touch(credential.id, credential.pubkey)
        return env
    def _post(self, kind, body):
        env = self._accept(sign(self.key, kind, self.device.id, body))
        with self.lock:
            self.posts.append((kind, body["id"]))
        if kind == "chunk":
            chunk = parse_chunk(env.body)
            return self.relay.feed(chunk.id, chunk.seq, chunk.data)
        out, tail = parse_result(env.body)
        if tail and not self.relay.feed(tail.id, tail.seq, tail.data):
            return False
        return self.relay.close(env.body["id"], out)
    def _execute(self, req, cancel):
        out, tail = run(req, self.policy, lambda seq, data: self._post("chunk", dict(id=req.id, seq=seq, data=base64.b64encode(data).decode())), cancel=cancel)
        body = dict(id=req.id, **(asdict(out) | {"state": out.state.value}))
        if tail:
            body.update(seq=tail.seq, data=base64.b64encode(tail.data).decode())
        self._post("result", body)
        with self.lock:
            self.running.pop(req.id, None)
    def _loop(self):
        try:
            while not self.stop.is_set():
                with self.lock:
                    running = list(self.running)
                self._accept(sign(self.key, "poll", self.device.id, {"running": running}))
                req, cancels = self.relay.next(self.device.id, 0.05, running=running, pubkey=self.device.pubkey)
                body = {"exec": {k: getattr(req, k) for k in WireExec.__annotations__}} if req else {}
                env = verify(self.relay_key.verify_key, sign(self.relay_key, "poll", "relay", body | {"cancel": cancels}),
                             int(time.time()), self.guard)
                req, cancels = parse_poll(env.body)
                with self.lock:
                    for rid in cancels:
                        if event := self.running.get(rid):
                            event.set()
                    if req:
                        self.running[req.id] = event = threading.Event()
                        self.futures.append(self.pool.submit(self._execute, req, event))
        except Exception as exc:
            self.errors.append(exc)
    def __enter__(self):
        self._accept(sign(self.key, "poll", self.device.id, {}))
        self.thread.start()
        return self
    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(1)
        with self.lock:
            for event in self.running.values():
                event.set()
        self.pool.shutdown(wait=True)
        for future in self.futures:
            future.result()
        if self.errors:
            raise self.errors[0]
