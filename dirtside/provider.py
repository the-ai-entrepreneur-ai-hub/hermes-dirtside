"""Resolve a conversation's target without falling back from an explicit device."""
import threading

from agent.terminal_env_provider import TerminalEnvironmentProvider
from gateway.session_context import get_session_env
from tools.environments.base import EnvironmentConnectionError
from tools.environments.local import LocalEnvironment

from .environment import DirtsideEnvironment, require_online
from .model import OnDevice, Server, SessionKey

def session_identity():
    return SessionKey(get_session_env("HERMES_SESSION_KEY") or get_session_env("HERMES_SESSION_ID"))

def resolve_target(session_key, is_cron, default_target, registry, relay, *, require_contact=True):
    chosen = registry.target(session_key) if session_key else None
    if chosen == "server":
        return Server()
    default = None if is_cron or default_target == "server" else registry.active_device(default_target)
    device = registry.device_by_id(chosen) if chosen else default
    if device is None and chosen:
        raise EnvironmentConnectionError("Dirtside: this conversation's device is no longer paired.",
                                         retry_hint="Run /dirtside use server, or pair the device again.")
    if device is None:
        return Server()
    if require_contact:
        require_online(device, relay)
    return OnDevice(device)

class ConversationEnvironment:
    # Core caches this object; file operations must not latch a host-filesystem shortcut.
    _persistent = True
    uses_host_filesystem = is_local = False

    def __init__(self, provider, key, cron, cwd, timeout, task_id):
        self._provider, self._key, self._cron = provider, key, cron
        self._cwd, self._timeout, self._task_id = cwd, timeout, task_id
        self._environments, self._lock = {}, threading.RLock()
        self._current(True)

    def _current(self, require_contact=False):
        p = self._provider
        target = resolve_target(self._key, self._cron, p._default_target, p._registry, p._relay,
                                require_contact=require_contact)
        identity = target.device if isinstance(target, OnDevice) else "server"
        with self._lock:
            if identity not in self._environments:
                self._environments[identity] = (
                    DirtsideEnvironment(p._relay, target.device, self._key, self._task_id, self._cwd, self._timeout)
                    if isinstance(target, OnDevice)
                    else LocalEnvironment(cwd="" if self._cwd == "~" else self._cwd, timeout=self._timeout))
            self._last = self._environments[identity]
            return self._last

    def __getattr__(self, name):
        delegate = (self._current(name == "execute") if name in {
            "execute", "_run_bash", "init_session", "get_temp_dir", "fetch_file", "fetch_realpath",
        } else self.__dict__.get("_last"))
        return getattr(delegate, name)

    @property
    def cwd(self):
        return self._last.cwd

    @cwd.setter
    def cwd(self, value):
        self._current().cwd = value

    def cleanup(self):
        for env in self._environments.values():
            env.cleanup()

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
        return ConversationEnvironment(self, session_identity(), get_session_env("HERMES_CRON_SESSION") == "1",
                                       cwd, timeout, task_id)
