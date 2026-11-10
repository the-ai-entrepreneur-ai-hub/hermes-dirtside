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
from contextvars import ContextVar
from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from hermes_cli.dashboard_auth import get_provider
from nacl.signing import SigningKey, VerifyKey

# Lazy threads; 64 online devices per gateway, with feeds on an independent pool.
POLL_POOL = ThreadPoolExecutor(max_workers=64, thread_name_prefix="dirtside-poll")
FEED_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="dirtside-feed")
_PAIR_LOCK, _OWNER_LOCK = threading.Lock(), threading.Lock()
_BOUND = ContextVar("dirtside_api_runtime", default=None)
_ORIGIN = None

def runtime():
    return _BOUND.get() or get_provider("dirtside")

def __getattr__(name):
    names = {"auth": None, "registry": "registry", "relay": "relay", "wire": "protocol", "model": "model"}
    if name == "relay_key":
        return SigningKey(runtime().registry.relay_seed)
    if name not in names:
        raise AttributeError(name)
    return getattr(runtime(), names[name]) if names[name] else runtime()

CHUNK_BODY_BYTES = 4 * ((runtime().model.PART_MAX + 2) // 3) + 1024
RESULT_BODY_BYTES = CHUNK_BODY_BYTES + 1024

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
        if (origin, pid, runtime().relay) == _ORIGIN:
            return
        if runtime().relay._owner_pid != pid:
            runtime().registry.mark_stale_lost(int(time.time()))
        path = runtime().registry.path.with_name("owner.json")
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".owner-", delete=False) as stream:
            json.dump(dict(origin=origin, pid=pid, started=runtime().process_started(pid)), stream)
            temporary = stream.name
        os.replace(temporary, path)
        runtime().relay._owner_pid, _ORIGIN = pid, (origin, pid, runtime().relay)

class BoundaryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def checked(request):
            provider = get_provider("dirtside")
            if provider is None:
                raise HTTPException(401, "Dirtside token routes are disabled")
            provider.local.require_routes()
            request.state.dirtside_auth = provider
            token = _BOUND.set(provider)
            try:
                return await handler(request)
            except PermissionError:
                raise HTTPException(401, "device revoked") from None
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise HTTPException(400, "invalid message") from None
            except provider.connection_error as exc:
                raise HTTPException(503, str(exc)) from None
            finally:
                _BOUND.reset(token)
        return checked

router = APIRouter(route_class=BoundaryRoute)
runtime().local.mount(router)

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

def verified(data, credential, kind, parser, token):
    data = json.loads(data)
    key = (base64.b64decode(data["body"]["pubkey"], validate=True)
           if isinstance(credential, runtime().model.Pending) else credential.pubkey)
    env = runtime().protocol.verify(VerifyKey(key), data, int(time.time()), runtime().protocol.GATEWAY_REPLAYS)
    sender = credential.name if isinstance(credential, runtime().model.Pending) else credential.id
    if env.kind != kind or env.sender != sender:
        raise ValueError("message identity mismatch")
    if isinstance(credential, runtime().model.Device):
        credential = runtime().registry.credential_for(token, int(time.time()), include_revoked=True)
    if credential is None:
        raise HTTPException(401, "unknown device credential")
    if isinstance(credential, runtime().model.Revoked):
        raise PermissionError("device revoked")
    if isinstance(credential, runtime().model.Device):
        runtime().relay.touch(credential.id, credential.pubkey)
    return credential, parser(env.body), env.body.get("id")

async def accepted(request, kind, parser):
    credential = await asyncio.to_thread(runtime().registry.credential_for, bearer(request), int(time.time()),
                                         include_revoked=True)
    retired = isinstance(credential, runtime().model.Revoked)
    if credential is None or (not retired and (kind == "hello") != isinstance(credential, runtime().model.Pending)):
        raise HTTPException(401, "unknown device credential")
    data = (await output_body(request, CHUNK_BODY_BYTES if kind == "chunk" else RESULT_BODY_BYTES)
            if kind in {"chunk", "result"} else await request.body())
    try:
        accepted = await asyncio.to_thread(verified, data, credential, kind, parser, bearer(request))
    except (ValueError, TypeError, KeyError, UnicodeError):
        if retired:
            raise HTTPException(401, "unknown device credential") from None
        raise
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
        previous = runtime().registry.active_device(name)
        device, token = runtime().registry.complete_pairing(name, hello, int(time.time()), code=code)
        if previous is not None and previous.id != device.id:
            runtime().relay.revoke(previous.id)
        runtime().relay.paired(device)
        return device, token

@router.post("/device/pair")
async def pair(request: Request):
    credential, hello, _ = await accepted(request, "hello", runtime().protocol.parse_hello)
    device, token = await asyncio.to_thread(complete_pairing, credential.name, hello, bearer(request))
    return dict(device_id=device.id, token=token, relay_pubkey=base64.b64encode(bytes(SigningKey(runtime().registry.relay_seed).verify_key)).decode())

@router.post("/device/poll")
async def poll(request: Request):
    device, running, _ = await accepted(request, "poll", runtime().protocol.parse_running)
    cancelled = threading.Event()
    waiting = asyncio.get_running_loop().run_in_executor(POLL_POOL, runtime().relay.next,
                                                        device.id, runtime().model.POLL_HOLD_S, cancelled, running, device.pubkey)
    # The core's receive wrapper needs a real await, not is_disconnected's cancelled probe.
    disconnected = asyncio.create_task(request.receive())
    disconnected.add_done_callback(lambda _: cancelled.set())
    try:
        req, cancels = await waiting
    finally:
        cancelled.set()
        disconnected.cancel()
        await asyncio.gather(disconnected, return_exceptions=True)
    body = {"exec": {k: getattr(req, k) for k in runtime().protocol.WireExec.__annotations__}} if req else {}
    return runtime().protocol.sign(SigningKey(runtime().registry.relay_seed), "poll", "relay", body | {"cancel": cancels})

@router.post("/device/chunk")
async def chunk(request: Request):
    device, part, _ = await accepted(request, "chunk", runtime().protocol.parse_chunk)
    return ack(await asyncio.get_running_loop().run_in_executor(FEED_POOL, runtime().relay.accept_chunk, device.id, part))

@router.post("/device/result")
async def result(request: Request):
    device, (outcome, tail), rid = await accepted(request, "result", runtime().protocol.parse_result)
    return ack(await asyncio.get_running_loop().run_in_executor(FEED_POOL, runtime().relay.accept_result, device.id, rid, outcome, tail))

@router.get("/devices")
async def devices():
    rows = await asyncio.to_thread(runtime().relay.connection().device_status)
    return [dict(id=d.id, name=d.name, online=online, os=d.os, home=d.home, last_seen=seen)
            for d, online, seen in rows]

@router.get("/sessions/{key}/target")
async def target(key: str):
    try:
        return {"target": await asyncio.to_thread(runtime().target_name, key)}
    except runtime().connection_error:
        raise HTTPException(404, "target device is no longer paired") from None

@router.put("/sessions/{key}/target")
async def set_target(key: str, request: Request):
    name = await field(request, "target")
    device = await asyncio.to_thread(runtime().registry.active_device, name) if name != "server" else None
    if name != "server" and device is None:
        raise HTTPException(404, "device is not paired")
    await asyncio.to_thread(runtime().registry.set_target, key, device.id if device else "server")
    return {"target": name}

@router.get("/requests")
async def requests(session_key: str | None = None):
    rows = await asyncio.to_thread(runtime().relay.connection().recent, 50, session_key)
    return [asdict(row) | {"tail": tail.decode("utf-8", "replace")} for row, tail in rows]

@router.post("/pairing")
async def pairing(request: Request):
    code = await asyncio.to_thread(runtime().registry.mint, await field(request, "name"), int(time.time()))
    return {"code": code}

@router.post("/devices/{name}/revoke")
async def revoke(name: str):
    device = await asyncio.to_thread(runtime().registry.revoke, name, int(time.time()))
    if device:
        await asyncio.to_thread(runtime().relay.connection().revoke, device.id)
    return {}
