"""Signed device transport and dashboard-session controls."""
import asyncio
import base64
import json
import os
import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from hermes_cli.dashboard_auth import get_provider
from nacl.signing import SigningKey, VerifyKey

# Lazy threads; 64 online devices per gateway, with feeds on an independent pool.
POLL_POOL = ThreadPoolExecutor(max_workers=64, thread_name_prefix="dirtside-poll")
FEED_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="dirtside-feed")
_PAIR_LOCK, _OWNER_LOCK = threading.Lock(), threading.Lock()
auth = get_provider("dirtside")
registry, relay, wire, model = auth.registry, auth.relay, auth.protocol, auth.model
CHUNK_BODY_BYTES = 4 * ((model.PART_MAX + 2) // 3) + 1024
RESULT_BODY_BYTES = CHUNK_BODY_BYTES + 1024
relay_key = SigningKey(registry.relay_seed)
_ORIGIN = None

def loopback_origin(request):
    host, port = request.scope.get("server") or ("127.0.0.1", 80)
    if ":" in host:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                pass
        except OSError:
            return f"http://[::1]:{port}"
    return f"http://127.0.0.1:{port}"

def record_owner(request):
    global _ORIGIN
    origin, pid = loopback_origin(request), os.getpid()
    with _OWNER_LOCK:
        if (origin, pid) == _ORIGIN:
            return
        if relay._owner_pid != pid:
            registry.mark_stale_lost(int(time.time()))
        path = registry.path.with_name("owner.json")
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".owner-", delete=False) as stream:
            json.dump(dict(origin=origin, pid=pid, started=auth.process_started(pid)), stream)
            temporary = stream.name
        os.replace(temporary, path)
        relay._owner_pid, _ORIGIN = pid, (origin, pid)

class BoundaryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def checked(request):
            auth.local.require_routes()
            try:
                return await handler(request)
            except PermissionError:
                raise HTTPException(401, "device revoked") from None
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise HTTPException(400, "invalid message") from None
            except auth.connection_error as exc:
                raise HTTPException(503, str(exc)) from None
        return checked

router = APIRouter(route_class=BoundaryRoute)
auth.local.mount(router)

def bearer(request):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" else ""

async def output_body(request, limit):
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > limit:
            raise HTTPException(413, "output part too large")
        data.extend(part)
    return data

def verified(data, credential, kind, parser):
    data = json.loads(data)
    key = (base64.b64decode(data["body"]["pubkey"], validate=True)
           if isinstance(credential, model.Pending) else credential.pubkey)
    env = wire.verify(VerifyKey(key), data, int(time.time()), wire.GATEWAY_REPLAYS)
    sender = credential.name if isinstance(credential, model.Pending) else credential.id
    if env.kind != kind or env.sender != sender:
        raise ValueError("message identity mismatch")
    if isinstance(credential, model.Device):
        relay.touch(credential.id, credential.pubkey)
    return credential, parser(env.body), env.body.get("id")

async def accepted(request, kind, parser):
    credential = await asyncio.to_thread(registry.credential_for, bearer(request), int(time.time()))
    if credential is None or (kind == "hello") != isinstance(credential, model.Pending):
        raise HTTPException(401, "unknown device credential")
    data = (await output_body(request, CHUNK_BODY_BYTES if kind == "chunk" else RESULT_BODY_BYTES)
            if kind in {"chunk", "result"} else await request.body())
    accepted = await asyncio.to_thread(verified, data, credential, kind, parser)
    await asyncio.to_thread(record_owner, request)
    return accepted

def ack(accepted):
    if not accepted:
        raise HTTPException(410, "request is terminal or unknown")
    return {}

async def field(request, name):
    body = await request.json()
    if type(body) is not dict or set(body) != {name} or type(body[name]) is not str:
        raise ValueError("invalid request body")
    return body[name]

def complete_pairing(name, hello, code):
    with _PAIR_LOCK:
        device, token = registry.complete_pairing(name, hello, int(time.time()), code=code)
        relay.paired(device)
        return device, token

@router.post("/device/pair")
async def pair(request: Request):
    credential, hello, _ = await accepted(request, "hello", wire.parse_hello)
    device, token = await asyncio.to_thread(complete_pairing, credential.name, hello, bearer(request))
    return dict(device_id=device.id, token=token, relay_pubkey=base64.b64encode(bytes(relay_key.verify_key)).decode())

@router.post("/device/poll")
async def poll(request: Request):
    device, running, _ = await accepted(request, "poll", wire.parse_running)
    cancelled = threading.Event()
    waiting = asyncio.get_running_loop().run_in_executor(POLL_POOL, relay.next,
                                                        device.id, model.POLL_HOLD_S, cancelled, running, device.pubkey)
    # The core's receive wrapper needs a real await, not is_disconnected's cancelled probe.
    disconnected = asyncio.create_task(request.receive())
    disconnected.add_done_callback(lambda _: cancelled.set())
    try:
        req, cancels = await waiting
    finally:
        cancelled.set()
        disconnected.cancel()
        await asyncio.gather(disconnected, return_exceptions=True)
    body = {"exec": {k: getattr(req, k) for k in wire.WireExec.__annotations__}} if req else {}
    return wire.sign(relay_key, "poll", "relay", body | {"cancel": cancels})

@router.post("/device/chunk")
async def chunk(request: Request):
    device, part, _ = await accepted(request, "chunk", wire.parse_chunk)
    return ack(await asyncio.get_running_loop().run_in_executor(FEED_POOL, relay.accept_chunk, device.id, part))

@router.post("/device/result")
async def result(request: Request):
    device, (outcome, tail), rid = await accepted(request, "result", wire.parse_result)
    return ack(await asyncio.get_running_loop().run_in_executor(FEED_POOL, relay.accept_result, device.id, rid, outcome, tail))

@router.get("/devices")
async def devices():
    rows = await asyncio.to_thread(relay.connection().device_status)
    return [dict(id=d.id, name=d.name, online=online, os=d.os, home=d.home, last_seen=seen)
            for d, online, seen in rows]

@router.get("/sessions/{key}/target")
async def target(key: str):
    chosen = await asyncio.to_thread(registry.target, key)
    device = await asyncio.to_thread(registry.device_by_id if chosen else registry.active_device, chosen or auth.default_target)
    if (chosen or auth.default_target) != "server" and device is None:
        raise HTTPException(404, "target device is no longer paired")
    return {"target": device.name if device else chosen or auth.default_target}

@router.put("/sessions/{key}/target")
async def set_target(key: str, request: Request):
    name = await field(request, "target")
    device = await asyncio.to_thread(registry.active_device, name) if name != "server" else None
    if name != "server" and device is None:
        raise HTTPException(404, "device is not paired")
    await asyncio.to_thread(registry.set_target, key, device.id if device else "server")
    return {"target": name}

@router.get("/requests")
async def requests(session_key: str | None = None):
    rows = await asyncio.to_thread(relay.connection().recent, 50, session_key)
    return [asdict(row) | {"tail": tail.decode("utf-8", "replace")} for row, tail in rows]

@router.post("/pairing")
async def pairing(request: Request):
    code = await asyncio.to_thread(registry.mint, await field(request, "name"), int(time.time()))
    return {"code": code}

@router.post("/devices/{name}/revoke")
async def revoke(name: str):
    device = await asyncio.to_thread(registry.revoke, name, int(time.time()))
    if device:
        await asyncio.to_thread(relay.connection().revoke, device.id)
    return {}
