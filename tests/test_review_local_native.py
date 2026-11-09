"""Real same-uid gateway sessions: CLI subprocess and TUI native RPC, with local model/device."""
import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing

import httpx
import pytest
from core_rig import CORE, install, stop_process, until
from hermes_cli.gateway_client import private_control_query
from tests.waiting import async_wait_until
from websockets.asyncio.client import connect

from dirtside.registry import Registry

CLI_SLASH = """
import contextlib, io, sys
from cli import HermesCLI
with contextlib.redirect_stdout(io.StringIO()):
    cli = HermesCLI(resume=sys.argv[1], compact=True, verbose=False)
    cli._ensure_gateway_session()
try:
    assert cli.session_id == sys.argv[1], cli.session_id
    cli.process_command(sys.argv[2])
finally:
    cli._session_db.connection.close()
"""


def control(home, verb, params=None):
    request = json.dumps({"protocol": 1, "id": 1, "verb": verb, "params": params or {}}).encode() + b"\n"
    reply = json.loads(private_control_query(home, request))
    assert reply["ok"], reply
    return reply["result"]


def websocket(home, desc):
    grant = control(home, "session-ticket", {"profile_id": str(home), "instance_id": desc["instance_id"],
                                           "purpose": "interactive"})
    return connect(desc["api_origin"].replace("http:", "ws:") + "/api/ws",
                   subprotocols=["hermes-gateway-v1", "hermes-gateway-ticket." + grant["ticket"]])


async def rpc(ws, method, **params):
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": method, "method": method, "params": params}))
    async with asyncio.timeout(20):
        while True:
            reply = json.loads(await ws.recv())
            if reply.get("id") == method:
                return reply


class TerminalModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages = body.get("messages", [])
        if messages:
            self.server.requests.append(body)
        last = messages[-1] if messages else {"role": "assistant", "content": "ready"}
        message = {"role": "assistant", "content": last["content"]}
        finish = "stop"
        if last["role"] == "user" and last["content"].startswith("RUN "):
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "native-terminal", "type": "function",
                "function": {"name": "terminal", "arguments": json.dumps({"command": last["content"][4:]})}}]}
            finish = "tool_calls"
        choice = {"index": 0, "message": message, "finish_reason": finish}
        kind = "application/json"
        if body.get("stream"):
            if message.get("tool_calls"):
                message["tool_calls"][0]["index"] = 0
            choice = {"index": 0, "delta": message, "finish_reason": finish}
            payload = ("data: " + json.dumps({"id": "native-stub", "choices": [choice]})
                       + "\n\ndata: [DONE]\n\n").encode()
            kind = "text/event-stream"
        else:
            payload = json.dumps({"id": "native-stub", "choices": [choice],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def native_gateway(tmp_path):
    home, work, device = (tmp_path / name for name in ("gateway", "work", "device"))
    work.mkdir()
    env = install(home, user_home=work)
    device_env = install(device)
    model = ThreadingHTTPServer(("127.0.0.1", 0), TerminalModel)
    model.requests = []
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{model.server_port}/v1"
    cfg = json.loads((home / "config.yaml").read_text())
    cfg.update(gateway={"multiplex_profiles": False},
               model={"provider": "custom", "default": "native-stub", "base_url": url, "api_mode": "chat_completions"},
               auxiliary={"title_generation": {"enabled": False}},
               memory={"enabled": False})
    (home / "config.yaml").write_text(json.dumps(cfg))
    (home / "models_dev_cache.json").write_text(json.dumps({"offline-stub": {"id": "offline-stub", "models": {}}}))
    env.update(OPENAI_API_KEY="loopback-only", OPENAI_BASE_URL=url)
    agent = None
    try:
        with (home / "gateway.log").open("w") as gateway_log:
            process = subprocess.Popen([sys.executable, "-m", "gateway.run"], cwd=CORE, env=env,
                                       stdin=subprocess.DEVNULL, stdout=gateway_log, stderr=subprocess.STDOUT)
            try:
                def ready():
                    assert process.poll() is None, (home / "gateway.log").read_text()
                    try:
                        desc = control(home, "identify")
                        return desc if desc.get("state") == "ready" else None
                    except (OSError, ValueError):
                        return None
                desc = until(ready, timeout=35)
                api = desc["api_origin"] + "/api/plugins/dirtside"
                headers = {"Authorization": "Bearer " + env["HERMES_DASHBOARD_SESSION_TOKEN"]}
                code = httpx.post(api + "/pairing", headers=headers, json={"name": "native-box"},
                                  trust_env=False).json()["code"]
                paired = subprocess.run([str(Path(sys.executable).with_name("hermes")), "dirtside", "pair",
                                         desc["api_origin"], "--name", "native-box", "--code=" + code],
                                        cwd=device, env=device_env, capture_output=True, text=True, timeout=40)
                assert paired.returncode == 0, paired.stdout + paired.stderr
                with (device / "agent.log").open("w") as log:
                    agent = subprocess.Popen([sys.executable, "-m", "dirtside.agent"], cwd=device, env=device_env,
                                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    until(lambda: any(d["online"] for d in httpx.get(
                        api + "/devices", headers=headers, trust_env=False).json()), timeout=20)
                    yield home, work, device, env, desc, model
            finally:
                stop_process(agent)
                process.send_signal(signal.SIGINT)
                process.wait(timeout=20)
    finally:
        model.shutdown()
        model.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("surface", ["cli", "tui"])
def test_native_local_demo(native_gateway, surface):
    home, work, device, env, desc, model = native_gateway
    server_dir, device_dir = work / "server-state", device / "device-state"
    server_dir.mkdir()
    device_dir.mkdir()

    async def exercise():
        async with websocket(home, desc) as ws:
            created = await rpc(ws, "session.create", request_id="native-demo", source=surface,
                                cwd=str(work), toolsets=["terminal"])
            assert "result" in created, created
            sid = created["result"]["session_id"]

            def cli(text):
                slash = text.startswith("/")
                command = ([sys.executable, "-c", CLI_SLASH, sid, text] if slash else
                           [str(Path(sys.executable).with_name("hermes")), "chat", "-c", sid, "-Q", "-q", text])
                result = subprocess.run(command,
                                        cwd=work, env=env, capture_output=True, text=True, timeout=45)
                assert result.returncode == 0, result.stdout + result.stderr
                return result.stdout

            async def slash(arg=""):
                if surface == "cli":
                    return await asyncio.to_thread(cli, "/dirtside" + (" " + arg if arg else ""))
                result = await rpc(ws, "slash.exec", session_id=sid, command="dirtside " + arg)
                assert "result" in result, result
                return result["result"]["output"]

            serial = 0

            async def turn(command):
                nonlocal serial
                serial += 1
                if surface == "cli":
                    await asyncio.to_thread(cli, "RUN " + command)
                else:
                    input_id = "native-turn-" + str(serial)
                    reply = await rpc(ws, "prompt.submit", session_id=sid, input_id=input_id, text="RUN " + command)
                    assert reply["result"]["status"] == "queued", reply

                    def terminal():
                        with closing(sqlite3.connect(home / "state.db")) as db:
                            row = db.execute("SELECT status FROM session_admissions WHERE request_id=?", (input_id,)).fetchone()
                        return row is not None and row[0] == "terminal"

                    await async_wait_until(terminal, timeout=30, what="native terminal turn")
                snapshot = await rpc(ws, "session.resume", session_id=sid)
                return json.loads(snapshot["result"]["messages"][-1]["content"])

            status = await slash()
            assert "Sender:local." in "".join(status.split())
            assert "native-box" in await slash("devices")
            state = "printf '%s|%s' \"$PWD\" \"${DIRTSIDE_C3_VALUE-unset}\""
            setup = f"cd {shlex.quote(str(server_dir))}; export DIRTSIDE_C3_VALUE=server; " + state
            assert (await turn(setup))["output"] == f"{server_dir}|server"
            assert "native-box" in await slash("use native-box")
            assert (await turn(state))["output"] == f"{device / 'user'}|unset"
            marker = device_dir / "ran-on-device"
            setup = f"cd {shlex.quote(str(device_dir))}; export DIRTSIDE_C3_VALUE=device; touch ran-on-device; " + state
            assert (await turn(setup))["output"] == f"{device_dir}|device"
            assert marker.exists()
            await slash("use server")
            assert (await turn(state))["output"] == f"{server_dir}|server"
            await slash("use native-box")
            assert (await turn(state))["output"] == f"{device_dir}|device"
            registry = Registry(home / "plugin-data/dirtside/data.db")
            paired = registry.active_device("native-box")
            assert paired.owner == "local"
            assert any(row.device_id == paired.id and row.exit_code == 0
                       for row in registry.recent(50))
            assert "Revoked native-box" in await slash("revoke native-box")
            forbidden = work / "must-not-run"
            refused = await turn("touch " + shlex.quote(str(forbidden)))
            assert refused["exit_code"] != 0 and "no longer paired" in refused["error"], refused
            assert not forbidden.exists()
            assert len(model.requests) >= 12

    asyncio.run(exercise())
