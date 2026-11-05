"""Pair, run and inspect this installation's personal device agent."""
import base64
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from nacl.signing import SigningKey, VerifyKey
from .agent.activity import recent_activity
from .agent.config import DeviceConfig, default_policy, device_path, gateway_url, policy_data
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
    service = actions.add_parser("install-service", help="Install a persistent per-user device service")
    service.add_argument("--dry-run", action="store_true", help="Print the unit without changing anything")
    service.add_argument("--remove", action="store_true", help="Remove the installed user service")

def service_spec(system, executable, home, state):
    log = state / "dirtside" / "service.log"
    env = dict(HOME=str(home), HERMES_HOME=str(state), PATH=os.environ.get("PATH", "/usr/bin:/bin"))
    args = [executable, "dirtside", "serve"]
    if system == "Darwin":
        path = home / "Library/LaunchAgents/ai.hermes.dirtside.plist"
        unit = plistlib.dumps(dict(Label="ai.hermes.dirtside", ProgramArguments=args,
                                   KeepAlive={"SuccessfulExit": False}, RunAtLoad=True,
                                   EnvironmentVariables=env, StandardOutPath=str(log), StandardErrorPath=str(log))).decode()
        domain = f"gui/{os.getuid()}"
        return path, unit, log, "launchctl", [["bootstrap", domain, str(path)]], ["bootout", domain, str(path)]
    if system != "Linux":
        raise ValueError("user services require macOS or Linux")
    def quote(value):
        if "\n" in value or "\r" in value:
            raise ValueError("service values cannot contain line breaks")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    path = home / ".config/systemd/user/hermes-dirtside.service"
    command = " ".join(quote(a).replace("$", "$$") for a in args)
    variables = " ".join(quote(k + "=" + v) for k, v in env.items())
    unit = "\n".join(("[Unit]", "Description=Hermes Dirtside device", "", "[Service]", "Type=simple",
                      f"ExecStart={command}", f"Environment={variables}", "Restart=on-failure", "RestartSec=2",
                      "UMask=0077", f"StandardOutput=append:{str(log).replace('%', '%%')}",
                      f"StandardError=append:{str(log).replace('%', '%%')}", "", "[Install]", "WantedBy=default.target", ""))
    return path, unit, log, "systemctl", [["--user", "daemon-reload"], ["--user", "enable", "--now", path.name]], ["--user", "disable", "--now", path.name]

def service_active(manager, tool, path):
    queries = [["print", f"gui/{os.getuid()}/ai.hermes.dirtside"]] if tool == "launchctl" else [
        ["--user", probe, "--quiet", path.name] for probe in ("is-enabled", "is-active")]
    return not manager or all(subprocess.run([manager, *query], capture_output=True).returncode == 0 for query in queries)

def write_service(path, unit, log):
    path.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    for target, content in ((log, None), (path, unit)):
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if content is None else os.O_TRUNC)
        with os.fdopen(os.open(target, flags, 0o600), "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            if content is not None:
                stream.write(content)

def install_service(args):
    executable = shutil.which("hermes") or str(Path(sys.executable).with_name("hermes"))
    path, unit, log, tool, loads, unload = service_spec(
        platform.system(), executable, Path.home(), device_path().parents[1])
    if args.dry_run:
        print(unit, end="")
        return
    manager = shutil.which(tool)
    exists = path.exists()
    if exists and manager and (args.remove or path.read_text() != unit):
        stopped = subprocess.run([manager, *unload], capture_output=True)
        if stopped.returncode not in (0, 3 if tool == "launchctl" else 5):
            stopped.check_returncode()
    if args.remove:
        path.unlink(missing_ok=True)
        if exists and manager and tool == "systemctl":
            subprocess.run([manager, "--user", "daemon-reload"], check=True)
        return
    if exists and path.read_text() == unit and service_active(manager, tool, path):
        return
    write_service(path, unit, log)
    for command in loads if manager else []:
        subprocess.run([manager, *command], check=True)
    print(f"Dirtside service written to {path}" + ("" if manager else f"; {tool} absent, not loaded"))

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
        if args.dirtside_action == "install-service":
            return install_service(args)
        cfg = DeviceConfig.load()
        return {"serve": serve, "status": status}[args.dirtside_action](cfg)
    except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError, subprocess.CalledProcessError) as exc:
        message = ("Pairing failed. Check the URL and mint a fresh pairing code." if args.dirtside_action == "pair" else "Service installation failed."
                   if args.dirtside_action == "install-service" else "Cannot load device configuration. Pair this device first.")
        print(f"Dirtside: {message} ({type(exc).__name__})")
        return 1
