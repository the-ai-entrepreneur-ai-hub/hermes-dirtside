"""Pair, run and inspect this installation's personal device agent."""
import base64
import platform
import re
import tempfile
import time
from pathlib import Path
import httpx
from nacl.signing import SigningKey, VerifyKey

from .agent.activity import recent_activity
from .agent.config import DeviceConfig, default_policy, gateway_url, policy_data
from .agent.loop import DEVICE_API, serve
from .model import OFFLINE_AFTER_S
from .protocol import sign

def setup_parser(parser):
    actions = parser.add_subparsers(dest="dirtside_action", required=True)
    pairing = actions.add_parser("pair", help="Pair this device with a gateway")
    pairing.add_argument("gateway_url")
    pairing.add_argument("--name", required=True)
    pairing.add_argument("--code", required=True)
    actions.add_parser("serve", help="Run the paired device agent in the foreground")
    actions.add_parser("status", help="Show pairing, policy and recent local activity")

def pair(args):
    url = gateway_url(args.gateway_url)
    if not re.fullmatch(r"[a-z0-9-]{1,32}", args.name):
        raise ValueError("invalid device name")
    key = SigningKey.generate()
    body = dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name=args.name,
                os=platform.system(), arch=platform.machine(), home=str(Path.home()),
                temp_dir=tempfile.gettempdir(), agent_version="0.1.0")
    with httpx.Client(base_url=url + "/", headers={"Authorization": f"Bearer {args.code}"}, timeout=35) as client:
        response = client.post(DEVICE_API + "pair", json=sign(key, "hello", args.name, body))
        response.raise_for_status()
        data = response.json()
    cfg = DeviceConfig(url, data["device_id"], data["token"], key,
                       VerifyKey(base64.b64decode(data["relay_pubkey"], validate=True)), args.name, default_policy())
    cfg.save()
    print(f"Paired {cfg.name} to {url}. Run 'hermes dirtside serve' to connect.")

def status(cfg):
    events = recent_activity()
    contact = max((e["time"] for e in events if e["event"] == "contact"), default=0)
    online = contact >= time.time() - OFFLINE_AFTER_S
    online = online and bool(events) and events[-1]["event"] not in {"stopped", "revoked"}
    print(f"{cfg.name}: paired to {cfg.gateway_url}, {'online' if online else 'offline'}")
    policy = policy_data(cfg.policy)
    print(f"Policy: {len(policy['deny_patterns'])} deny patterns, timeout {policy['max_timeout_s']}s, "
          f"output {policy['max_output_bytes']} bytes, parallel {policy['max_parallel']}")
    for event in events:
        if "id" in event:
            print(f"{event['event']} {event['id']} exit={event.get('exit_code', '-')}")

def handle(args):
    try:
        if args.dirtside_action == "pair":
            return pair(args)
        cfg = DeviceConfig.load()
        return {"serve": serve, "status": status}[args.dirtside_action](cfg)
    except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
        message = ("Pairing failed. Check the URL and mint a fresh pairing code."
                   if args.dirtside_action == "pair" else "Cannot load device configuration. Pair this device first.")
        print(f"Dirtside: {message} ({type(exc).__name__})")
        return 1
