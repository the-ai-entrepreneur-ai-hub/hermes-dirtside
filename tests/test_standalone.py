"""A real local install and signed terminal path without a device-side core."""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_rig import Rig

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {"hermes_constants", "hermes_cli", "plugins", "tools", "gateway", "run_agent", "agent"}
BLOCKER = """
import importlib.abc, sys
class BlockCore(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in BLOCKED:
            raise ModuleNotFoundError(fullname, name=fullname)
sys.meta_path.insert(0, BlockCore())
"""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    for key in ("HOME", "HERMES_HOME"):
        path = tmp_path / key.lower()
        path.mkdir()
        monkeypatch.setenv(key, str(path))
    monkeypatch.delenv("DIRTSIDE_HOME", raising=False)


def python(code, *args):
    return subprocess.run([sys.executable, "-I", "-c", textwrap.dedent(code), str(ROOT), *args],
                          capture_output=True, text=True, timeout=30)


def test_device_imports_without_core():
    result = python("BLOCKED = " + repr(BLOCKED) + "\n" + BLOCKER + """
sys.path.insert(0, sys.argv[1])
import dirtside, dirtside.cli, dirtside.agent.loop, dirtside.protocol
assert not BLOCKED.intersection(sys.modules)
""")
    assert result.returncode == 0, result.stderr


def test_isolated_homes_ignore_state_override(tmp_path, monkeypatch):
    outer = tmp_path / "outer-pairing"
    outer.mkdir()
    saved = outer / "device.json"
    saved.write_bytes(b"existing-pairing")
    monkeypatch.setenv("DIRTSIDE_HOME", str(outer))
    collection = python("""
import os, runpy, sys
from pathlib import Path
scope = runpy.run_path(str(Path(sys.argv[1]) / 'conftest.py'))
print('clean' if 'DIRTSIDE_HOME' not in os.environ else 'inherited')
""")
    assert collection.returncode == 0, collection.stderr
    with Rig(tmp_path / "rig") as rig:
        rig.pair()
        inherited = "DIRTSIDE_HOME" in rig.device_env
        assert not inherited, "The rig inherited the outer state override"
        assert (rig.device_home / "dirtside/device.json").is_file()
    assert collection.stdout.strip() == "clean"
    assert saved.read_bytes() == b"existing-pairing"


def test_state_location_order_and_legacy_pairing(tmp_path, monkeypatch):
    from dirtside.agent.config import DeviceConfig, default_policy, device_path
    from nacl.signing import SigningKey
    import hermes_constants
    legacy = tmp_path / "legacy"
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: legacy)
    cfg = DeviceConfig("https://gateway.example", "a" * 32, "fake-device-token",
                       SigningKey.generate(), SigningKey.generate().verify_key, "old", default_policy())
    cfg.save(legacy / "dirtside/device.json")
    original = (legacy / "dirtside/device.json").read_bytes()
    override = tmp_path / "override"
    monkeypatch.setenv("DIRTSIDE_HOME", str(override))
    assert device_path() == override / "device.json"
    monkeypatch.delenv("DIRTSIDE_HOME")
    assert device_path() == legacy / "dirtside/device.json"
    assert DeviceConfig.load() == cfg
    assert device_path().read_bytes() == original
    result = python("BLOCKED = " + repr(BLOCKED) + "\n" + BLOCKER + """
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from dirtside.agent.config import device_path
assert device_path() == Path.home() / '.dirtside/device.json', device_path()
""")
    assert result.returncode == 0, result.stderr


def test_relative_state_resolves_before_service_changes_directory(tmp_path, monkeypatch):
    from dirtside.agent.config import DeviceConfig, default_policy, device_path
    from dirtside.agent.home import service_environment
    from nacl.signing import SigningKey
    pairing, serving = tmp_path / "pairing", tmp_path / "serving"
    pairing.mkdir()
    serving.mkdir()
    monkeypatch.chdir(pairing)
    monkeypatch.setenv("DIRTSIDE_HOME", "device-state")
    path = device_path()
    assert path == pairing / "device-state/device.json"
    cfg = DeviceConfig("https://gateway.example", "a" * 32, "fake-device-token",
                       SigningKey.generate(), SigningKey.generate().verify_key, "relative", default_policy())
    cfg.save()
    original = path.read_bytes()
    env = service_environment(tmp_path / "profile")
    assert env["DIRTSIDE_HOME"] == str(path.parent)
    monkeypatch.setenv("DIRTSIDE_HOME", env["DIRTSIDE_HOME"])
    monkeypatch.chdir(serving)
    result = python("BLOCKED = " + repr(BLOCKED) + "\n" + BLOCKER + """
sys.path.insert(0, sys.argv[1])
from dirtside.agent.console import main
sys.argv = ['dirtside-agent', 'status']
raise SystemExit(main())
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("relative: paired to https://gateway.example, offline\n")
    assert DeviceConfig.load() == cfg and path.read_bytes() == original
    assert not (serving / "device-state").exists()


@pytest.mark.parametrize("action", ["status", "serve", "policy", "pair"])
def test_unknown_home_user_reports_one_line(monkeypatch, action):
    monkeypatch.setenv("DIRTSIDE_HOME", "~dirtside-no-such-user-16c0b58a/state")
    args = ([action, "https://gateway.example", "--name", "phone", "--code=fake"]
            if action == "pair" else [action])
    result = python("BLOCKED = " + repr(BLOCKED) + "\n" + BLOCKER + """
sys.path.insert(0, sys.argv[1])
from dirtside.agent.console import main
sys.argv = ['dirtside-agent', *sys.argv[2:]]
raise SystemExit(main())
""", *args)
    message = ("Pairing failed. Check the URL and mint a fresh pairing code." if action == "pair" else
               "Cannot load device configuration. Pair this device first.")
    assert result.returncode == 1
    assert result.stdout == f"Dirtside: {message} (RuntimeError)\n"
    assert result.stderr == ""


def test_legacy_service_keeps_override_and_profile(tmp_path, monkeypatch, capsys):
    import plistlib
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from dirtside import cli
    profile = tmp_path / "selected-profile"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIRTSIDE_HOME", "device-state")
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/test/bin/hermes")
    units = {}
    scope = set_hermes_home_override(profile)
    try:
        for system in ("Darwin", "Linux"):
            monkeypatch.setattr(cli.platform, "system", lambda: system)
            cli.install_service(SimpleNamespace(dry_run=True, remove=False))
            units[system] = capsys.readouterr().out
    finally:
        reset_hermes_home_override(scope)
    plist = plistlib.loads(units["Darwin"].encode())
    env = plist["EnvironmentVariables"]
    assert env["HERMES_HOME"] == str(profile)
    assert env.get("DIRTSIDE_HOME") == str(tmp_path / "device-state")
    assert plist["StandardOutPath"] == str(tmp_path / "device-state/service.log")
    assert f'"HERMES_HOME={profile}"' in units["Linux"]
    assert f'"DIRTSIDE_HOME={tmp_path / "device-state"}"' in units["Linux"]
    assert str(tmp_path / "device-state/service.log") in units["Linux"]
    assert not (tmp_path / "device-state").exists(), "Dry run wrote state"


@pytest.fixture
def installed(tmp_path):
    source = tmp_path / "install-source"
    source.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", source)
    shutil.copytree(ROOT / "dirtside", source / "dirtside", ignore=shutil.ignore_patterns("__pycache__"))
    venv = tmp_path / "clean-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
    py = venv / "bin/python"
    try:
        result = subprocess.run([str(py), "-m", "pip", "install", str(source)], capture_output=True,
                                text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        packages = subprocess.check_output([str(py), "-m", "pip", "list", "--format=json"], text=True)
        names = {p["name"].lower() for p in json.loads(packages)}
        print("Clean install packages:", ", ".join(sorted(names)))
        assert not any("hermes" in name for name in names)
        assert {"httpx", "pynacl"} <= names
        yield venv
    finally:
        shutil.rmtree(venv)
        shutil.rmtree(source)


def device_rig(tmp_path, installed):
    command = [sys.executable, str(ROOT / "tests/standalone_device.py"), str(installed / "bin/dirtside-agent")]
    return Rig(tmp_path / "rig", device_command=command)


def test_standalone_install_signed_terminal_and_revoke(tmp_path, installed):
    with device_rig(tmp_path, installed) as rig:
        rig.pair().start_agent().choose()
        result = rig.core.terminal('printf "standalone:%s" "$HOME"', timeout=5)
        assert result["exit_code"] == 0, result
        assert result["output"] == "standalone:" + rig.device_env["HOME"]
        assert (Path(rig.device_env["HOME"]) / ".dirtside/device.json").is_file()
        assert rig.core.http("POST", "/devices/laptop/revoke").status_code == 200
        assert rig.agent.wait(8) == 0


def test_home_dotenv_is_not_loaded(tmp_path, installed, monkeypatch):
    monkeypatch.delenv("PROVIDER_KEY", raising=False)
    report = tmp_path / "agent-environment.json"
    adapter = tmp_path / "observe-agent.py"
    adapter.write_text(textwrap.dedent(f"""
        import atexit, json, os, runpy, sys
        from pathlib import Path
        if sys.argv[-1] == "serve":
            atexit.register(lambda: Path({str(report)!r}).write_text(json.dumps(
                {{key: key in os.environ for key in ("PROVIDER_KEY", "DIRTSIDE_ENV_PROBE")}})))
            sys.argv = sys.argv[1:]
            runpy.run_path(sys.argv[0], run_name="__main__")
        else:
            runpy.run_path({str(ROOT / "tests/standalone_device.py")!r}, run_name="__main__")
    """))
    project = subprocess.check_output([str(installed / "bin/python"), "-I", "-c",
        "from pathlib import Path; import dirtside; print(Path(dirtside.__file__).resolve().parent.parent)"],
        text=True).strip()
    command = [str(installed / "bin/python"), "-I", str(adapter), str(installed / "bin/dirtside-agent")]
    with Rig(tmp_path / "rig", device_command=command) as rig:
        # Core reads the explicit/default Hermes home and its installed project root, not HOME/.env.
        locations = (Path(rig.device_env["HERMES_HOME"]), Path(rig.device_env["HOME"]) / ".hermes", Path(project))
        for location in locations:
            location.mkdir(exist_ok=True)
            (location / ".env").write_text("PROVIDER_KEY=not-a-real-provider-key\n")
        rig.device_env["DIRTSIDE_ENV_PROBE"] = "inherited-control"
        rig.pair().start_agent().choose()
        result = rig.core.terminal("printf agent-ran", timeout=5)
        assert result["exit_code"] == 0, result
        assert rig.core.http("POST", "/devices/laptop/revoke").status_code == 200
        assert rig.agent.wait(8) == 0
        assert json.loads(report.read_text()) == {"PROVIDER_KEY": False, "DIRTSIDE_ENV_PROBE": True}


def test_console_and_pairing_guidance(tmp_path, capsys, monkeypatch):
    import argparse
    from dirtside.cli import pair, setup_parser
    import dirtside.cli as cli
    parser = argparse.ArgumentParser(prog="dirtside-agent")
    setup_parser(parser, standalone=True)
    help_text = parser.format_help()
    assert "install-service" not in help_text
    for action in ("serve", "status", "policy"):
        assert parser.parse_args([action]).command_prefix == "dirtside-agent"
    key = cli.SigningKey.generate()
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: dict(
        device_id="b" * 32, token="fake", relay_pubkey=cli.base64.b64encode(bytes(key.verify_key)).decode()))
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def post(self, *args, **kwargs):
            return response
    monkeypatch.setattr(cli.httpx, "Client", Client)
    monkeypatch.setenv("DIRTSIDE_HOME", str(tmp_path / "state"))
    pair(parser.parse_args(["pair", "https://gateway.example", "--name", "phone", "--code=fake"]))
    assert "Run 'dirtside-agent serve'" in capsys.readouterr().out
    from dirtside.commands import Commands
    from dirtside.registry import Registry
    from dirtside.relay import Relay
    registry = Registry(tmp_path / "gateway.db")
    reply = Commands(SimpleNamespace(), registry, Relay(registry))("pair phone")
    assert "dirtside-agent pair" in reply and "hermes dirtside pair" in reply


def test_pipx_local_install(tmp_path, installed):
    py = installed / "bin/python"
    result = subprocess.run([str(py), "-m", "pip", "install", "pipx>=1,<2"], capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(PIPX_HOME=str(tmp_path / "pipx"), PIPX_BIN_DIR=str(tmp_path / "bin"),
               PIPX_MAN_DIR=str(tmp_path / "man"))
    try:
        source = tmp_path / "install-source"
        result = subprocess.run([str(py), "-m", "pipx", "install", "--python", str(py), str(source)],
                                env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        run = subprocess.run([str(tmp_path / "bin/dirtside-agent"), "--help"],
                             env=env, capture_output=True, text=True, timeout=10)
        assert run.returncode == 0 and "pair" in run.stdout, run.stdout + run.stderr
    finally:
        shutil.rmtree(tmp_path / "pipx", ignore_errors=True)
