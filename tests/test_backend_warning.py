"""Configuration warnings through real slash dispatch and the public hook."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_rig import Rig

FIX = "hermes config set terminal.backend dirtside"
WARNING = ('Configured terminal.backend is "local"; commands will not run on the device until you run '
           + FIX + " and restart the gateway.")
FALLBACK = ('Terminal backend is "{backend}" because terminal.backend is not set; '
            'commands will not run on the device until you run ' + FIX + " and restart the gateway.")
MODES = ["local", "dirtside", "missing", "empty", "unreadable", "non-string", "env-dirtside", "env-docker"]
WARNINGS = {"local": WARNING, "missing": FALLBACK.format(backend="local"),
            "empty": FALLBACK.format(backend="local"), "env-docker": FALLBACK.format(backend="docker")}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("command,raw_args", [("dirtside", "use laptop"), ("land", "laptop")])
def test_config_warning_in_real_selection_and_hook(tmp_path, mode, command, raw_args):
    with Rig(tmp_path / "rig") as rig:
        rig.pair()
        rig.restart_gateway()
        params = dict(command=command, raw_args=raw_args, session="chat")
        original = rig.core.call("slash", **params)
        original_facts = rig.core.call("turn_facts", session="chat")
        assert len(original_facts) == 1 and 'device="laptop"' in original_facts[0]
        path = rig.core.home / "config.yaml"
        config = json.loads(path.read_text())
        if mode == "unreadable":
            path.unlink()
            path.mkdir()
        else:
            assert "TERMINAL_ENV" not in rig.core.env
            if mode in ("missing", "env-dirtside", "env-docker"):
                del config["terminal"]["backend"]
            else:
                config["terminal"]["backend"] = {"empty": "", "non-string": 7}.get(mode, mode)
            if mode.startswith("env-"):
                rig.core.env["TERMINAL_ENV"] = " " + mode.removeprefix("env-") + " \t"
            path.write_text(json.dumps(config) + "\n")
            rig.restart_gateway()
        assert rig.core.call("slash", command="orbit", raw_args="", session="chat") == (
            "Back in orbit. Commands run on the server.")
        if mode in ("local", "missing", "empty", "env-docker"):
            assert rig.core.info["backend"].strip() == {"empty": "", "env-docker": "docker"}.get(mode, "local")
        reply = rig.core.call("slash", **params)
        facts = rig.core.call("turn_facts", session="chat")
        warning = WARNINGS.get(mode)
        expected = (original + " " + warning, [warning]) if warning else (original, original_facts)
        assert (reply, facts) == expected
        assert all(len(line) <= 600 and len(line.splitlines()) == 1 for line in facts)
        assert rig.core.call("turn_facts", session="untouched") == []
        assert rig.core.call("turn_facts", session="chat", platform="telegram", source="telegram",
                             user_id="visitor") == []
        orbit = rig.core.call("slash", command="orbit", raw_args="", session="chat")
        assert orbit == "Back in orbit. Commands run on the server."
        assert rig.core.call("turn_facts", session="chat") == [
            "Dirtside target: server. Commands run on the server."]
        server = rig.core.call("slash", command="dirtside", raw_args="use server", session="chat")
        assert server == ("This conversation now targets server. "
                          "The change applies to this conversation from the next command.")


def device_hook(monkeypatch):
    import dirtside.awareness as awareness
    from dirtside.model import OnDevice
    device = SimpleNamespace(name="private-device", os="private-os", home="/private-device-home")
    monkeypatch.setattr(awareness, "resolve_target", lambda *a, **kw: OnDevice(device))
    return awareness.TargetAwareness(None, None)


@pytest.mark.parametrize("source", ["configuration", "environment"])
def test_config_warning_quotes_and_bounds_value(monkeypatch, source):
    from hermes_cli import config
    value = 'local\n\u2028"quoted"' + "x" * 10000
    raw = {"terminal": {"backend": value}} if source == "configuration" else {}
    monkeypatch.setattr(config, "read_raw_config_readonly", lambda: raw)
    monkeypatch.setenv("TERMINAL_ENV", value)
    line = device_hook(monkeypatch)()
    assert FIX in line and "restart the gateway" in line and '"local' in line
    assert len(line) <= 600 and len(line.splitlines()) == 1
    assert all(value not in line for value in ("device=", "OS=", "home=", "private-device"))


@pytest.mark.parametrize("file_state", ["missing", "unparseable"])
def test_empty_file_result_warns_default_backend(tmp_path, monkeypatch, file_state):
    from hermes_cli import config
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    if file_state == "unparseable":
        (tmp_path / "config.yaml").write_text("terminal: [")
    assert config.read_raw_config_readonly() == {}
    assert device_hook(monkeypatch)() == FALLBACK.format(backend="local")


@pytest.mark.parametrize("failure", [OSError, SystemExit])
def test_unreadable_reader_keeps_existing_facts(monkeypatch, failure):
    from hermes_cli import config
    def unreadable():
        raise failure("unreadable test config")
    monkeypatch.setattr(config, "read_raw_config_readonly", unreadable)
    line = device_hook(monkeypatch)()
    assert 'device="private-device"' in line and 'home="/private-device-home"' in line
    assert FIX not in line


def test_offline_hint_names_both_device_entrypoints():
    from dirtside.environment import EnvironmentConnectionError, require_online
    device = SimpleNamespace(id="offline-device", name="laptop")
    relay = SimpleNamespace(connection=lambda: SimpleNamespace(is_online=lambda device_id: False))
    with pytest.raises(EnvironmentConnectionError) as error:
        require_online(device, relay)
    hint = error.value.retry_hint
    assert "dirtside-agent serve" in hint and "hermes dirtside serve" in hint
    assert "/dirtside use server" in hint


def test_readme_command_replies_and_device_entrypoints(monkeypatch):
    from dirtside import commands
    from hermes_cli import config
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    sample = readme.split("## Sixty seconds with it", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
    pair = sample.split("hermes   ", 1)[1].split("\nlaptop $", 1)[0]
    use = sample.split("you      /dirtside use macbook\nhermes   ", 1)[1].split("\n\nyou", 1)[0]
    code = re.search(r"Pairing code (\S+)", pair)[1]
    device = SimpleNamespace(id="sample-device", owner="local", name="macbook", os="Darwin", home="/Users/you")
    registry = SimpleNamespace(mint=lambda *a, **kw: code, owners_for_name=lambda name: [],
                               active_device=lambda name: device, set_target=lambda *a: None)
    relay = SimpleNamespace(connection=lambda: SimpleNamespace(is_online=lambda device_id: True))
    monkeypatch.setattr(commands, "session_identity", lambda: "sample-conversation")
    monkeypatch.setattr(config, "read_raw_config_readonly", lambda: {"terminal": {"backend": "dirtside"}})
    handler = commands.Commands(SimpleNamespace(), registry, relay)
    actual = (handler("pair macbook"), handler("use macbook"))
    assert tuple(" ".join(reply.split()) for reply in actual) == (
        " ".join(pair.split()), " ".join(use.split()))
    quick_start = readme.split("### Pair in four commands", 1)[1].split("Codes expire", 1)[0]
    for verb in ("pair", "serve"):
        assert "dirtside-agent " + verb in quick_start and "hermes dirtside " + verb in quick_start
    assert quick_start.count("plugin installed and enabled on this device") == 2


@pytest.mark.parametrize("selection", ["saved", "default"])
@pytest.mark.parametrize("mode", MODES)
def test_frozen_prompt_uses_authorized_backend_warning(tmp_path, selection, mode):
    with Rig(tmp_path / "rig") as rig:
        rig.pair()
        path = rig.core.home / "config.yaml"
        config = json.loads(path.read_text())
        if selection == "saved":
            rig.choose()
        else:
            config["plugins"]["entries"]["dirtside"]["settings"]["default_target"] = "laptop"
            path.write_text(json.dumps(config) + "\n")
            rig.restart_gateway()
        original = rig.core.call("prompt", session="chat")
        assert len(original) == 1 and 'device="laptop"' in original[0]
        if mode == "unreadable":
            path.unlink()
            path.mkdir()
        else:
            assert "TERMINAL_ENV" not in rig.core.env
            if mode in ("missing", "env-dirtside", "env-docker"):
                del config["terminal"]["backend"]
            else:
                config["terminal"]["backend"] = {"empty": "", "non-string": 7}.get(mode, mode)
            if mode.startswith("env-"):
                rig.core.env["TERMINAL_ENV"] = " " + mode.removeprefix("env-") + " \t"
            path.write_text(json.dumps(config) + "\n")
            rig.restart_gateway()
        frozen = rig.core.call("prompt", session="chat", snapshot="fresh")
        warning = WARNINGS.get(mode)
        assert frozen == ([warning] if warning else original)
        assert all(len(line) <= 600 and len(line.splitlines()) == 1 for line in frozen)
        if mode == "unreadable":
            assert rig.core.call("prompt", session="chat") == original
        denied = rig.core.call("prompt", session="chat", snapshot="unauthorized", platform="telegram",
                               source="telegram", user_id="visitor")
        assert all(value not in str(denied) for value in ("laptop", "device=", "OS=", "home=", FIX))
        rig.core.call("slash", raw_args="use server", session="chat")
        assert rig.core.call("prompt", session="chat", snapshot="server") == []
