"""Termux defaults come from the observed userland and app system names."""
import os
import platform
import subprocess
from dataclasses import replace

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))


def test_termux_detection_and_environment(monkeypatch):
    from dirtside.agent.config import default_policy
    from dirtside.agent.executor import child_environment
    from dirtside.agent.platform import device_os, is_termux
    env = dict(PREFIX="/data/data/com.termux/files/usr", PATH="/termux/bin",
               LD_PRELOAD="/termux/lib/libtermux-exec-ld-preload.so", ANDROID_ROOT="/system",
               ANDROID_DATA="/data", ANDROID_RUNTIME_ROOT="/apex", BOOTCLASSPATH="/system/framework",
               EXTERNAL_STORAGE="/sdcard", TZ="Africa/Nairobi", DEVICE_SETTING="chosen")
    monkeypatch.setattr(os, "environ", env)
    assert is_termux() and device_os() == "Android (Termux)"
    assert child_environment(default_policy()) == {k: v for k, v in env.items() if k != "DEVICE_SETTING"}
    assert child_environment(replace(default_policy(), env_passthrough=("DEVICE_SETTING",))) == env
    monkeypatch.setitem(env, "PREFIX", "/data/user/0/com.termux/files/usr")
    assert is_termux()


def test_other_platform_environment_unchanged(monkeypatch):
    from dirtside.agent.config import default_policy
    from dirtside.agent.executor import child_environment
    from dirtside.agent.platform import device_os, is_termux
    env = dict(PATH="/bin", HOME="/home/device", USER="device", LANG="C", LC_ALL="C", LC_TIME="C",
               TERM="xterm", TMPDIR="/tmp", PREFIX="/opt/local", LD_PRELOAD="unrelated",
               ANDROID_ROOT="/system", TZ="UTC", DEVICE_SETTING="chosen")
    monkeypatch.setattr(os, "environ", env)
    assert not is_termux() and device_os() == platform.system()
    expected = {k: env[k] for k in ("PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_TIME", "TERM", "TMPDIR")}
    assert child_environment(default_policy()) == expected
    expected["DEVICE_SETTING"] = "chosen"
    assert child_environment(replace(default_policy(), env_passthrough=("DEVICE_SETTING",))) == expected


def test_termux_default_names_exclude_secrets(monkeypatch):
    import re
    from dirtside.agent.config import default_policy
    from dirtside.agent.executor import child_environment
    from dirtside.agent.platform import TERMUX_SYSTEM_NAMES
    forbidden = ("ANDROID_KEY", "ANDROID_TOKEN", "TERMUX_SECRET", "TERMUX_PASSWORD", "ANDROID_AUTH",
                 "PREFIX_SECRET", "LD_PRELOAD_TOKEN")
    env = {name: "fake-not-a-credential" for name in forbidden}
    env.update(PREFIX="/data/data/com.termux/files/usr", LD_PRELOAD="/termux/lib/exec.so")
    monkeypatch.setattr(os, "environ", env)
    assert not any(re.search("KEY|TOKEN|SECRET|PASSWORD|AUTH", name, re.I) for name in TERMUX_SYSTEM_NAMES)
    assert set(child_environment(default_policy())) == {"PREFIX", "LD_PRELOAD"}
    # Explicit device policy remains an opt-in, not a default.
    from dataclasses import replace
    assert "ANDROID_KEY" in child_environment(replace(default_policy(), env_passthrough=("ANDROID_KEY",)))


def test_pairing_reports_termux(tmp_path, monkeypatch):
    import argparse
    import base64
    import json
    import httpx
    from nacl.signing import SigningKey
    from dirtside import cli
    sent = []
    def reply(request):
        sent.append(json.loads(request.content)["body"])
        return httpx.Response(200, json=dict(device_id="c" * 32, token="fake",
                              relay_pubkey=base64.b64encode(bytes(SigningKey.generate().verify_key)).decode()))
    make_client = httpx.Client
    monkeypatch.setattr(cli.httpx, "Client", lambda **kw: make_client(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setenv("DIRTSIDE_HOME", str(tmp_path / "state"))
    parser = argparse.ArgumentParser()
    cli.setup_parser(parser)
    cli.pair(parser.parse_args(["pair", "https://gateway.example", "--name", "phone", "--code=fake"]))
    assert sent[0]["os"] == "Android (Termux)"


def test_termux_loopback_forward():
    import base64
    import json
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    import httpx
    path = Path(__file__).resolve().parents[1] / "tools/termux_forward.py"
    proc = subprocess.Popen([sys.executable, "-u", str(path)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready = proc.stdout.readline()
        assert ready, proc.stderr.read()
        port = json.loads(ready)["port"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(httpx.post, f"http://127.0.0.1:{port}/signed", content=b"signed-bytes",
                                 headers={"Authorization": "Bearer fake"}, timeout=5, trust_env=False)
            frame = json.loads(proc.stdout.readline())
            assert frame["path"] == "/signed" and frame["authorization"] == "Bearer fake"
            assert base64.b64decode(frame["body"]) == b"signed-bytes"
            proc.stdin.write(json.dumps(dict(id=frame["id"], status=201,
                                            body=base64.b64encode(b'{"accepted":true}').decode())) + "\n")
            proc.stdin.flush()
            result = future.result(8)
            assert result.status_code == 201 and result.json() == {"accepted": True}
    finally:
        proc.stdin.close()
        try:
            proc.wait(8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(3)
        proc.stdout.close()
        proc.stderr.close()
