"""Signed Termux lifecycle check using a uniquely named container."""
import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from core_rig import ROOT, Rig, until

TMP = "/data/data/com.termux/files/usr/tmp"
EXEC = ["docker", "exec", "--user", "system"]


def step(*args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def device(name, action):
    args = ["dirtside-agent", action]
    if action == "pair":
        data = json.load(sys.stdin)
        args += [data["gateway_url"], "--name", data["name"], "--code=" + data["code"]]
    command = [*EXEC, "-i", name, "env",
               "LD_PRELOAD=/data/data/com.termux/files/usr/lib/libtermux-exec-ld-preload.so", *args]
    if action == "pair":
        result = subprocess.run(command, capture_output=True, text=True)
        Path("termux-pair.log").write_text(result.stdout + result.stderr)
        print(result.stdout + result.stderr, end="")
        return result.returncode
    os.execvp(command[0], command)


class Forward:
    def __init__(self, name, url):
        self.url, self.lock = url, threading.Lock()
        self.proc = subprocess.Popen([*EXEC, "-i", name, "python", "-u", TMP + "/forward.py"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.port = json.loads(self.proc.stdout.readline())["port"]
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        for line in self.proc.stdout:
            self.pool.submit(self.forward, json.loads(line))

    def forward(self, data):
        try:
            with httpx.Client(timeout=40, trust_env=False) as client:
                response = client.post(self.url + data["path"], content=base64.b64decode(data["body"]),
                                       headers={"Authorization": data["authorization"],
                                                "Content-Type": "application/json"})
            status, body = response.status_code, response.content
        except httpx.HTTPError:
            status, body = 502, b'{"detail":"test forward failed"}'
        with self.lock:
            self.proc.stdin.write(json.dumps(dict(id=data["id"], status=status,
                                                  body=base64.b64encode(body).decode())) + "\n")
            self.proc.stdin.flush()

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(50)
        self.reader.join(2)
        self.pool.shutdown(wait=True)
        self.proc.stdout.close()


def test_termux_signed_path(root, name):
    command = [sys.executable, str(Path(__file__).resolve()), "--device", name]
    with Rig(root, name="phone", device_command=command) as rig:
        forward = Forward(name, rig.core.url)
        try:
            rig.public_url = f"http://127.0.0.1:{forward.port}"
            print("Container loopback gateway:", rig.public_url, flush=True)
            rig.pair().start_agent().choose()
            print((rig.device_home / "termux-pair.log").read_text(), flush=True)
            rows = rig.core.http("GET", "/devices").json()
            assert next(d for d in rows if d["name"] == "phone")["os"] == "Android (Termux)", rows
            commands = [
                ("printf '#!/usr/bin/env bash\\nprintf shebang-ran\\n' > \"$HOME/check.sh\"; "
                 "chmod +x \"$HOME/check.sh\"; \"$HOME/check.sh\"", "shebang-ran", 0),
                ("python3 -c 'print(\"python-ran\")'", "python-ran", 0),
                ('echo "$PREFIX"', "/data/data/com.termux/files/usr", 0),
                ("printf expected-failure; exit 7", "expected-failure", 7),
            ]
            for script, output, code in commands:
                result = rig.core.terminal(script, timeout=10)
                print("terminal", script, json.dumps(result), flush=True)
                assert result["exit_code"] == code and result["output"] == output, result
            script = "printf cancel-ready; sleep 60; :"
            future = rig.core.submit("terminal", session="chat", args=dict(command=script, timeout=75))
            until(lambda: any(r["preview"] == script and r["tail"]
                              for r in rig.core.http("GET", "/requests").json()), timeout=10)
            rig.core.call("interrupt", call_id=future.call_id)
            result = future.result(10)
            print("cancel", json.dumps(result), flush=True)
            assert result["exit_code"] == 130 and "cancel-ready" in result["output"], result
            response = rig.core.http("POST", "/devices/phone/revoke")
            print("revoke", response.status_code, response.text, flush=True)
            assert response.status_code == 200
            assert rig.agent.wait(10) == 0
            print("PASS: Termux signed path; Termux:API and a physical phone were not tested.", flush=True)
        finally:
            try:
                rig.stop_agent()
                log = rig.device_home / "agent-process.log"
                if log.exists():
                    print(log.read_text(), flush=True)
            finally:
                forward.close()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--device":
        return device(*sys.argv[2:])
    os.environ.setdefault("DOCKER_CONFIG", str(Path.home() / ".docker"))
    name = "dirtside-termux-" + secrets.token_hex(6)
    created = False
    try:
        step("docker", "run", "--rm", "-d", "--name", name, "--cpus=2", "--memory=1g",
             "--security-opt", "seccomp:unconfined", "termux/termux-docker:aarch64",
             "bash", "-lc", f"touch {TMP}/ready; while :; do sleep 60; done")
        created = True
        until(lambda: subprocess.run([*EXEC, name, "test", "-f", TMP + "/ready"],
                                     capture_output=True).returncode == 0, timeout=120)
        step(*EXEC, name, "bash", "-lc", f"apt-get update && apt-get install -y python python-pynacl git && mkdir -p {TMP}/dirtside-source")
        for part in ("pyproject.toml", "dirtside"):
            step("docker", "cp", ROOT / part, f"{name}:{TMP}/dirtside-source/{part}")
        step("docker", "cp", ROOT / "tools/termux_forward.py", f"{name}:{TMP}/forward.py")
        step("docker", "exec", name, "chown", "-R", "system:system", f"{TMP}/dirtside-source", f"{TMP}/forward.py")
        probe = "python -c 'import nacl; print(nacl.__version__, nacl.__file__)'"
        step(*EXEC, name, "bash", "-lc",
             f"before=$({probe}) && echo \"Before pip: $before\" && python -m pip install {TMP}/dirtside-source && "
             f"python -m pip list && after=$({probe}) && echo \"After pip: $after\" && test \"$before\" = \"$after\" && "
             "python -c 'import sys; assert sys.prefix == sys.base_prefix' && "
             "test -f \"$PREFIX/lib/libtermux-exec-ld-preload.so\"")
        with tempfile.TemporaryDirectory(prefix="dirtside-termux-") as temp:
            test_termux_signed_path(Path(temp), name)
    finally:
        if created:
            print("+ cleanup", name, flush=True)
            subprocess.run(["docker", "rm", "-f", name], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
