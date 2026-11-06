"""Private, bounded loopback routes for independently loaded workers."""
import asyncio
import base64
import hmac
import ipaddress
import json
import os
import re
import select
import sqlite3
import struct
from dataclasses import asdict
from anyio import CancelScope
from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse
from .model import CHUNK_BYTES, ExecRequest, Outcome, RequestState
from .protocol import parse_exec

BODY_BYTES = 8 << 20
PREFIX = "/api/plugins/dirtside/local"

async def body(request):
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > BODY_BYTES:
            raise HTTPException(413, "local body too large")
        data.extend(part)
    return json.loads(data)

class LocalAPI:
    def __init__(self, registry, relay):
        self.registry, self.relay = registry, relay

    def mount(self, router):
        for path, handler, methods in (
            ("/exec", self.execute, ["POST"]), ("/stream", self.stream, ["GET"]),
            ("/kill", self.kill, ["POST"]), ("/devices", self.devices, ["GET"]),
            ("/devices", self.revoke, ["POST"]), ("/requests", self.recent, ["GET"]),
        ):
            router.add_api_route("/local" + path, handler, methods=methods)

    def authenticate(self, request):
        try:
            peer = ipaddress.ip_address(request.client.host if request.client else "")
        except ValueError:
            raise HTTPException(403, "local peer required") from None
        if not (getattr(peer, "ipv4_mapped", None) or peer).is_loopback:
            raise HTTPException(403, "local peer required")
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), self.registry.local_secret.encode()):
            raise HTTPException(401, "local credential required")

    def owner(self, id=None):
        if id is not None and not re.fullmatch(r"r_[0-9a-f]{24}", id):
            raise ValueError("invalid request id")
        if self.relay.connection() is not self.relay:
            raise HTTPException(409, "this server is not the device owner")

    async def execute(self, request: Request):
        self.authenticate(request)
        data = await body(request)
        if type(data) is not dict:
            raise ValueError("invalid execution")
        extra = {k: data[k] for k in ("device_id", "session_key", "task_id")}
        if not all(type(v) is str and len(v) <= 4096 and "\0" not in v for v in extra.values()):
            raise ValueError("invalid local identity")
        parse_exec({k: v for k, v in data.items() if k not in extra})
        if not re.fullmatch("[0-9a-f]{32}", extra["device_id"]):
            raise ValueError("invalid device id")
        self.owner()
        device = await asyncio.to_thread(self.registry.device_by_id, extra["device_id"])
        if device is None or not self.relay.is_online(device.id):
            raise HTTPException(409, "device is unavailable")
        try:
            handle = await asyncio.to_thread(self.relay.submit_local, ExecRequest(**data))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "request already submitted") from None
        return {"state": handle.state.value}

    async def stream(self, id: str, request: Request):
        self.authenticate(request)
        self.owner(id)
        handle = self.relay.take_stream(id)
        if handle is None:
            raise HTTPException(410, "stream is consumed or unknown")
        return StreamingResponse(self.output(handle), media_type="application/octet-stream")

    async def output(self, handle):
        try:
            while True:
                ready = await asyncio.to_thread(select.select, [handle.stdout], [], [], 0.1)
                await asyncio.to_thread(handle.poll)
                if not ready[0]:
                    continue
                part = os.read(handle.stdout.fileno(), CHUNK_BYTES)
                if not part:
                    break
                yield struct.pack("!I", len(part))
                yield part
            yield b"\0\0\0\0" + json.dumps(asdict(handle.outcome) | {"state": handle.state.value}).encode() + b"\n"
        finally:
            handle.stdout.close()
            with CancelScope(shield=True):
                await asyncio.to_thread(self.relay.close, handle.req.id,
                                       Outcome(RequestState.LOST, 124, 0, False, "gateway stopped reading output"))

    async def kill(self, id: str, request: Request):
        self.authenticate(request)
        self.owner(id)
        await self.empty(request)
        with self.relay._condition:
            handle = self.relay.handles.get(id)
        await asyncio.to_thread(self.relay.kill, id)
        return {"cancelled": handle is not None and handle.state is RequestState.CANCELLED}

    async def empty(self, request):
        if await body(request) != {}:
            raise ValueError("empty object required")

    async def devices(self, request: Request):
        self.authenticate(request)
        return [dict(id=d.id, name=d.name, online=online, os=d.os, home=d.home, last_seen=seen)
                for d, online, seen in await asyncio.to_thread(self.relay.connection().device_status)]

    async def recent(self, request: Request, limit: int = 50, session_key: str | None = None):
        self.authenticate(request)
        rows = await asyncio.to_thread(self.relay.connection().recent, min(limit, 50), session_key)
        return [asdict(row) | {"tail": base64.b64encode(tail).decode()} for row, tail in rows]

    async def revoke(self, request: Request):
        self.authenticate(request)
        data = await body(request)
        if type(data) is not dict or set(data) != {"device_id"} or not re.fullmatch("[0-9a-f]{32}", data["device_id"]):
            raise ValueError("invalid device id")
        await asyncio.to_thread(self.relay.connection().revoke, data["device_id"])
        return {}
