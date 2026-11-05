"""Resolve a conversation's target without falling back from an explicit device."""
from agent.terminal_env_provider import TerminalEnvironmentProvider
from gateway.session_context import get_session_env
from tools.environments.base import EnvironmentConnectionError
from tools.environments.local import LocalEnvironment

from .environment import DirtsideEnvironment
from .model import OnDevice, Server, SessionKey

def session_identity():
    return SessionKey(get_session_env("HERMES_SESSION_KEY") or get_session_env("HERMES_SESSION_ID"))

def resolve_target(session_key, is_cron, default_target, registry, relay):
    chosen = registry.target_device_id(session_key) if session_key else None
    default = None if is_cron or default_target == "server" else registry.active_device(default_target)
    device = registry.device_by_id(chosen) if chosen else default
    if device is None and chosen:
        raise EnvironmentConnectionError("Dirtside: this conversation's device is no longer paired.",
                                         retry_hint="Run /dirtside use server, or pair the device again.")
    if device is None:
        return Server()
    if not relay.is_online(device.id):
        raise EnvironmentConnectionError(f"Dirtside: device '{device.name}' is offline.",
                                         retry_hint="Start hermes dirtside serve on it, or run /dirtside use server. Nothing was run on the server.")
    return OnDevice(device)

class DirtsideProvider(TerminalEnvironmentProvider):
    name = "dirtside"
    display_name = "Dirtside (your own devices)"
    is_remote = True
    is_container = False

    def __init__(self, registry, relay, default_target="server"):
        self._registry, self._relay, self._default_target = registry, relay, default_target

    @property
    def default_cwd(self):
        return "~"

    def is_available(self):
        return True

    def create_environment(self, *, cwd, timeout, task_id="default", image=None,
                           container_config=None, **kwargs):
        key = session_identity()
        target = resolve_target(key, get_session_env("HERMES_CRON_SESSION") == "1",
                                self._default_target, self._registry, self._relay)
        match target:
            case Server():
                return LocalEnvironment(cwd="" if cwd == "~" else cwd, timeout=timeout)
            case OnDevice(device):
                return DirtsideEnvironment(self._relay, device, key, task_id, cwd, timeout)
