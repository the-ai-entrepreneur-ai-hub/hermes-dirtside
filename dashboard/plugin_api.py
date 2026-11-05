"""Signed device transport and dashboard-session controls."""
import asyncio
import base64
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from hermes_cli.dashboard_auth import get_provider
from nacl.signing import SigningKey, VerifyKey

POLL_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="dirtside-poll")
auth = get_provider("dirtside")
registry, relay, wire, model = auth.registry, auth.relay, auth.protocol, auth.model
relay_key = SigningKey(registry.relay_seed)

class BoundaryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def checked(request):
            try:
                return await handler(request)
            except PermissionError:
                raise HTTPException(401, "device revoked") from None
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise HTTPException(400, "invalid message") from None
        return checked

router = APIRouter(route_class=BoundaryRoute)

def bearer(request):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" else ""

async def accepted(request, kind, parser):
    credential = await asyncio.to_thread(registry.credential_for, bearer(request), int(time.time()))
    if credential is None or (kind == "hello") != isinstance(credential, model.Pending):
        raise HTTPException(401, "unknown device credential")
    data = await request.json()
    key = (base64.b64decode(data["body"]["pubkey"], validate=True)
           if isinstance(credential, model.Pending) else credential.pubkey)
    env = wire.verify(VerifyKey(key), data, int(time.time()))
    sender = credential.name if isinstance(credential, model.Pending) else credential.id
    if env.kind != kind or env.sender != sender:
        raise ValueError("message identity mismatch")
    if isinstance(credential, model.Device):
        await asyncio.to_thread(relay.touch, credential.id)
    return credential, parser(env.body), env.body.get("id")

def empty(body):
    if body != {}:
        raise ValueError("poll body must be empty")

def ack(accepted):
    if not accepted:
        raise HTTPException(410, "request is terminal or unknown")
    return {}

async def field(request, name):
    body = await request.json()
    if type(body) is not dict or set(body) != {name} or type(body[name]) is not str:
        raise ValueError("invalid request body")
    return body[name]

@router.post("/device/pair")
async def pair(request: Request):
    credential, hello, _ = await accepted(request, "hello", wire.parse_hello)
    device, token = await asyncio.to_thread(registry.complete_pairing, credential.name, hello,
                                          int(time.time()), code=bearer(request))
    return dict(device_id=device.id, token=token, relay_pubkey=base64.b64encode(bytes(relay_key.verify_key)).decode())

@router.post("/device/poll")
async def poll(request: Request):
    device, _, _ = await accepted(request, "poll", empty)
    req, cancels = await asyncio.get_running_loop().run_in_executor(POLL_POOL, relay.next,
                                                                   device.id, model.POLL_HOLD_S)
    body = {"exec": {k: getattr(req, k) for k in wire.WireExec.__annotations__}} if req else {}
    return wire.sign(relay_key, "poll", "relay", body | {"cancel": cancels})

@router.post("/device/chunk")
async def chunk(request: Request):
    device, part, _ = await accepted(request, "chunk", wire.parse_chunk)
    return ack(await asyncio.get_running_loop().run_in_executor(POLL_POOL, relay.accept_chunk, device.id, part))

@router.post("/device/result")
async def result(request: Request):
    device, (outcome, tail), rid = await accepted(request, "result", wire.parse_result)
    return ack(await asyncio.to_thread(relay.accept_result, device.id, rid, outcome, tail))

@router.get("/devices")
async def devices():
    rows = await asyncio.to_thread(relay.device_status)
    return [dict(id=d.id, name=d.name, online=online, os=d.os, home=d.home, last_seen=seen)
            for d, online, seen in rows]

@router.get("/sessions/{key}/target")
async def target(key: str):
    chosen = await asyncio.to_thread(registry.target_device_id, key)
    device = await asyncio.to_thread(registry.device_by_id, chosen) if chosen and chosen != "server" else None
    if chosen and chosen != "server" and device is None:
        raise HTTPException(404, "target device is no longer paired")
    return {"target": device.name if device else chosen or auth.default_target}

@router.put("/sessions/{key}/target")
async def set_target(key: str, request: Request):
    name = await field(request, "target")
    device = await asyncio.to_thread(registry.active_device, name) if name != "server" else None
    if name != "server" and device is None:
        raise HTTPException(404, "device is not paired")
    await asyncio.to_thread(registry.set_target, key, device.id if device else None)
    return {"target": name}

@router.get("/requests")
async def requests(session_key: str | None = None):
    rows = await asyncio.to_thread(relay.recent, 50, session_key)
    return [asdict(row) | {"tail": tail.decode("utf-8", "replace")} for row, tail in rows]

@router.post("/pairing")
async def pairing(request: Request):
    code = await asyncio.to_thread(registry.mint, await field(request, "name"), int(time.time()))
    return {"code": code}

@router.post("/devices/{name}/revoke")
async def revoke(name: str):
    device = await asyncio.to_thread(registry.revoke, name, int(time.time()))
    if device:
        await asyncio.to_thread(relay.revoke, device.id)
    return {}
