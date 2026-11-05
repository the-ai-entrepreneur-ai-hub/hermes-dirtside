"""Shared signed envelopes and strict wire-body parsing."""
import base64
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, fields
from typing import get_args
from nacl.exceptions import BadSignatureError
from .model import CHUNK_BYTES, Outcome, RequestId, RequestState

PROTOCOL_VERSION = 1
class ProtocolError(ValueError):
    pass
@dataclass(frozen=True)
class Envelope:
    v: int
    kind: str
    sender: str
    ts: int
    nonce: str
    body: dict
    sig: bytes
@dataclass(frozen=True)
class DeviceHello:
    pubkey: bytes
    name: str
    os: str
    arch: str
    home: str
    temp_dir: str
    agent_version: str
@dataclass(frozen=True)
class WireExec:
    id: RequestId
    command: str
    script: str
    login: bool
    timeout_s: int
    stdin: str | None
    cwd: str
@dataclass(frozen=True)
class Chunk:
    id: RequestId
    seq: int
    data: bytes

def _need(ok, reason="invalid message shape"):
    if not ok:
        raise ProtocolError(reason)

def _record(cls, body):
    fs = fields(cls)
    _need(type(body) is dict and body.keys() == {f.name for f in fs})
    for f in fs:
        typ = getattr(f.type, "__supertype__", f.type)
        _need(type(body[f.name]) in (get_args(typ) or (typ,)), f"invalid {f.name}")
    return cls(**body)

def _bytes(value):
    _need(type(value) is str)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ProtocolError("invalid base64") from exc
    _need(len(data) <= CHUNK_BYTES, "output part too large")
    return data

def _id(value):
    _need(type(value) is str and re.fullmatch(r"r_[0-9a-f]{24}", value))
    return RequestId(value)

def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def sign(key, kind, sender, body):
    payload = dict(v=PROTOCOL_VERSION, kind=kind, sender=sender, ts=int(time.time()),
                   nonce=secrets.token_hex(16), body=body)
    return payload | {"sig": base64.b64encode(key.sign(canonical(payload)).signature).decode("ascii")}

class ReplayGuard:
    def __init__(self):
        self._seen, self._lock = OrderedDict(), threading.Lock()

    def check(self, sender, nonce, now):
        with self._lock:
            while self._seen and next(iter(self._seen.values())) < now - 300:
                self._seen.popitem(last=False)
            _need((sender, nonce) not in self._seen, "replayed message")
            self._seen[sender, nonce] = now
            if len(self._seen) > 4096:
                self._seen.popitem(last=False)

GATEWAY_REPLAYS = ReplayGuard()

def verify(pubkey, wire, now, guard=None):
    _need(type(wire) is dict)
    env = _record(Envelope, wire | {"sig": _bytes(wire.get("sig"))})
    _need(env.v == PROTOCOL_VERSION, "unsupported protocol version, expected 1")
    _need(env.kind in {"hello", "exec", "chunk", "result", "poll"} and abs(env.ts - now) <= 300)
    _need(re.fullmatch(r"[0-9a-f]{32}", env.nonce) and re.fullmatch(r"[\w-]{1,64}", env.sender))
    try:
        pubkey.verify(canonical({k: v for k, v in wire.items() if k != "sig"}), env.sig)
    except (BadSignatureError, ValueError, TypeError, UnicodeError) as exc:
        raise ProtocolError("invalid signature") from exc
    if guard is not None:
        guard.check(env.sender, env.nonce, now)
    return env

def parse_hello(body):
    _need(type(body) is dict)
    hello = _record(DeviceHello, body | {"pubkey": _bytes(body.get("pubkey"))})
    _need(len(hello.pubkey) == 32 and re.fullmatch(r"[a-z0-9-]{1,32}", hello.name))
    _need(all(p.startswith("/") and "\0" not in p for p in (hello.home, hello.temp_dir)))
    return hello

def parse_exec(body):
    req = _record(WireExec, body)
    _id(req.id)
    _need(req.timeout_s > 0 and req.cwd.startswith("/") and all("\0" not in s for s in (req.cwd, req.script, req.command)))
    return req

def parse_chunk(body):
    _need(type(body) is dict)
    chunk = _record(Chunk, body | {"data": _bytes(body.get("data"))})
    _id(chunk.id)
    _need(chunk.seq >= 0)
    return chunk

def parse_result(body):
    _need(type(body) is dict and set(body) - {"seq", "data"} == {"id", "state", "exit_code", "duration_ms", "truncated", "reason"})
    _id(body["id"])
    _need(body["state"] in ("finished", "refused") and ("seq" in body) == ("data" in body))
    out = _record(Outcome, {k: v for k, v in body.items() if k not in {"id", "seq", "data"}} | {"state": RequestState(body["state"])})
    _need(out.duration_ms >= 0)
    return out, parse_chunk({k: body[k] for k in ("id", "seq", "data")}) if "seq" in body else None

def parse_poll(body):
    _need(type(body) is dict and set(body) <= {"exec", "cancel"} and type(body.get("cancel", [])) is list)
    return parse_exec(body["exec"]) if "exec" in body else None, [_id(rid) for rid in body.get("cancel", [])]

def parse_running(body):
    _need(type(body) is dict and set(body) <= {"running"})
    _need("running" not in body or type(body["running"]) is list)
    return [_id(rid) for rid in body["running"]] if "running" in body else None
