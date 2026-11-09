"""Locate device state without requiring a gateway installation."""
import os
from pathlib import Path


def device_path():
    if home := os.environ.get("DIRTSIDE_HOME"):
        return Path(home).expanduser().resolve() / "device.json"
    try:
        from hermes_constants import get_hermes_home
    except ModuleNotFoundError as exc:
        if exc.name != "hermes_constants":
            raise
        return Path.home() / ".dirtside" / "device.json"
    return get_hermes_home() / "dirtside" / "device.json"


def service_environment(state):
    env = {"HERMES_HOME": str(state)}
    if home := os.environ.get("DIRTSIDE_HOME"):
        env["DIRTSIDE_HOME"] = str(Path(home).expanduser().resolve())
    return env
