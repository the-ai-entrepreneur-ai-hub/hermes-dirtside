"""Owned core and device processes, with isolated installed plugin homes."""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import Future
from contextlib import suppress
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORE = Path(os.environ.get("HERMES_SRC", ROOT.parent / "hermes-agent-main")).resolve()


def until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        threading.Event().wait(0.02)
    raise AssertionError("owned rig did not reach its expected state")


def install(home, backend="dirtside", user_home=None, token=None, public_url=None):
    home.mkdir(parents=True, mode=0o700, exist_ok=True)
    explicit_home = user_home
    user_home = user_home or home / "user"
    for path in (user_home, home / "tmp", home / "runtime"):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    plugin = home / "plugins" / "dirtside"
    plugin.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "plugin.yaml", "pyproject.toml"):
        shutil.copy2(ROOT / name, plugin / name)
    for name in ("dirtside", "dashboard"):
        shutil.copytree(ROOT / name, plugin / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    config = dict(plugins=dict(enabled=["dirtside"], disabled=[], isolation="in_process",
                               entries=dict(dirtside=dict(settings=dict(default_target="server")))),
                  terminal=dict(backend=backend, local_persistent=True),
                  dashboard=dict(public_url=public_url or "https://matrix.example.test"), file_read_max_chars=1_000_000)
    if explicit_home is not None:
        config["terminal"]["cwd"] = str(explicit_home)
    (home / "config.yaml").write_text(json.dumps(config) + "\n")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TERMINAL_", "HERMES_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))}
    env.update(HERMES_HOME=str(home), HOME=str(user_home), TMPDIR=str(home / "tmp"),
               HERMES_RUNTIME_DIR=str(home / "runtime"), TERMINAL_TEMP_DIR=str(home / "tmp"),
               PYTHONPATH=os.pathsep.join((str(CORE), str(ROOT), str(ROOT / "tools"))),
               PYTHONDONTWRITEBYTECODE="1", NO_PROXY="127.0.0.1,localhost",
               HERMES_DASHBOARD_SESSION_TOKEN=token or secrets.token_urlsafe(32))
    return env


def stop_process(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(12)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(3)


class Core:
    def __init__(self, home, backend="dirtside", user_home=None, port=0, env=None, public_url=None, worker=False):
        self.home = home
        self.env = env or install(home, backend, user_home, public_url=public_url)
        self.token = self.env["HERMES_DASHBOARD_SESSION_TOKEN"]
        self.log = (home / "core.log").open("a")
        ready = Future()
        self.lock, self.pending, self.serial = threading.Lock(), {"ready": ready}, 0
        command = [sys.executable, str(ROOT / "tests" / "core_runtime.py"), str(port)]
        self.proc = subprocess.Popen(command + (["--worker"] if worker else []),
                                     cwd=home, env=self.env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.log, text=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.info = ready.result(40)
        except BaseException:
            self.close()
            raise
        self.url = f"http://127.0.0.1:{self.info['port']}"

    def _read(self):
        try:
            for line in self.proc.stdout:
                message = json.loads(line)
                with self.lock:
                    future = self.pending.pop(message["id"])
                if "error" in message:
                    future.set_exception(AssertionError(message["error"]))
                else:
                    future.set_result(message["result"])
        finally:
            with self.lock:
                for future in self.pending.values():
                    future.set_exception(RuntimeError("owned core process stopped"))
                self.pending.clear()

    def submit(self, method, **params):
        with self.lock:
            self.serial += 1
            key, future = str(self.serial), Future()
            future.call_id = key
            self.pending[key] = future
            self.proc.stdin.write(json.dumps(dict(id=key, method=method, params=params)) + "\n")
            self.proc.stdin.flush()
        return future

    def call(self, method, wait=90, **params):
        timeout = (params.get("args") or {}).get("timeout")
        if timeout is not None:
            wait = timeout + 15
        return self.submit(method, **params).result(wait)

    def terminal(self, command, session="chat", **kwargs):
        return self.call("terminal", session=session, args=dict(command=command, **kwargs))

    def http(self, method, path, authenticated=True, **kwargs):
        headers = kwargs.pop("headers", {})
        if authenticated:
            headers = {"Authorization": "Bearer " + self.token, **headers}
        with httpx.Client(base_url=self.url, timeout=35, trust_env=False) as client:
            return client.request(method, "/api/plugins/dirtside" + path, headers=headers, **kwargs)

    def close(self):
        with suppress(BrokenPipeError):
            self.proc.stdin.close()
        if self.proc.poll() is None:
            try:
                self.proc.wait(18)
            except subprocess.TimeoutExpired:
                stop_process(self.proc)
        self.reader.join(3)
        self.proc.stdout.close()
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Rig:
    def __init__(self, root, name="laptop", port=0, url=None, device_command=None):
        self.root, self.name = root, name
        self.device_home = root / "device"
        self.device_env = install(self.device_home)
        self.agent, self.agent_log = None, None
        self.device_command = device_command
        self.core = Core(root / "gateway", port=port, public_url=url)
        self.public_url = url or self.core.url

    def pair(self):
        response = self.core.http("POST", "/pairing", json={"name": self.name})
        assert response.status_code == 200, response.text
        code = response.json()["code"]
        command = [str(Path(sys.executable).with_name("hermes")), "dirtside", "pair",
                   self.public_url, "--name", self.name, "--code=" + code]
        data = None
        if self.device_command:
            command = [*self.device_command, "pair"]
            data = json.dumps(dict(gateway_url=self.public_url, name=self.name, code=code))
        result = subprocess.run(command, input=data, cwd=self.device_home, env=self.device_env,
                                capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stdout + result.stderr
        self.config = (json.loads((self.device_home / "dirtside" / "device.json").read_text())
                       if not self.device_command else None)
        return self

    def start_agent(self):
        assert self.agent is None or self.agent.poll() is not None, "agent already running"
        self.agent_log = (self.device_home / "agent-process.log").open("a")
        command = [*self.device_command, "serve"] if self.device_command else [sys.executable, "-m", "dirtside.agent"]
        started = time.time()
        self.agent = subprocess.Popen(command, cwd=self.device_home, env=self.device_env,
                                       stdin=subprocess.PIPE if self.device_command else subprocess.DEVNULL,
                                       stdout=self.agent_log, stderr=subprocess.STDOUT, start_new_session=True)
        until(lambda: self.online(since=started), timeout=20)
        return self

    def online(self, since=0):
        rows = self.core.http("GET", "/devices").json()
        return any(row["name"] == self.name and row["online"] and row["last_seen"] >= since for row in rows)

    def choose(self, session="chat"):
        self.core.call("target", session=session, name=self.name)
        return self

    def stop_agent(self):
        if self.device_command and self.agent is not None:
            with suppress(BrokenPipeError):
                self.agent.stdin.close()
            if self.agent.poll() is None:
                try:
                    self.agent.wait(10)
                except subprocess.TimeoutExpired:
                    stop_process(self.agent)
        stop_process(self.agent)
        if self.agent_log is not None:
            self.agent_log.close()
            self.agent_log = None

    def restart_gateway(self):
        old = self.core
        port = old.info["port"]
        old.proc.kill()
        old.proc.wait(3)
        old.close()
        self.core = Core(old.home, port=port, env=old.env)

    def close(self):
        try:
            self.stop_agent()
        finally:
            self.core.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
