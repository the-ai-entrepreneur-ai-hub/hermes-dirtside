"""A user directory installation must load through the startup sweep and CLI."""
import json
import subprocess
import sys
from pathlib import Path

from core_rig import Core, ROOT, install


def test_startup_discovers_installed_provider_auth_and_cli(tmp_path):
    with Core(tmp_path / "installed") as core:
        info = core.info
        assert info["enabled"] and not info["error"], info
        assert info["source"] == "user"
        assert Path(info["path"]) == core.home / "plugins" / "dirtside"
        assert info["module"].startswith("hermes_plugins.")
        assert info["auth"] == "DirtsideDeviceAuth" and info["shared"]
        assert "dirtside" in info["cli"]
        assert info["backend"] == "dirtside" and info["gate"]
        executable = str(Path(sys.executable).with_name("hermes"))
        for args in (["plugins", "list"], ["plugins", "doctor", str(info["path"]), "--ci"]):
            result = subprocess.run([executable, *args], cwd=core.home, env=core.env,
                                    capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "dirtside" in result.stdout.lower()
        assert "registration passed" not in result.stderr


def test_directory_is_opt_in_and_disabled_wins(tmp_path):
    env = install(tmp_path)
    path = tmp_path / "config.yaml"
    config = json.loads(path.read_text())
    check = """
from hermes_cli.plugins import get_plugin_manager
from agent.terminal_env_registry import get_provider
m = get_plugin_manager()
m.discover_and_load()
assert get_provider("dirtside") is None
assert "dirtside" not in m._cli_commands
print("inactive installation stays inactive")
"""
    for enabled, disabled in (([], []), (["dirtside"], ["dirtside"])):
        config["plugins"].update(enabled=enabled, disabled=disabled)
        path.write_text(json.dumps(config))
        result = subprocess.run([sys.executable, "-c", check], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "inactive installation stays inactive" in result.stdout
