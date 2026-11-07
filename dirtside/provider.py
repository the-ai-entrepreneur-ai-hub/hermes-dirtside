"""Resolve a conversation's target without falling back from an explicit device."""
import threading
import weakref

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
    if device is None and (chosen or (not is_cron and default_target != "server")):
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

    def __init__(self, provider, key, cwd, timeout, task_id):
        self._provider, self._fallback_key = provider, key
        self._cwd, self._timeout, self._task_id = cwd, timeout, task_id
        self._environments, self._lock = {}, threading.RLock()
        self._current(True)

    def _current(self, require_contact=False):
        p = self._provider
        key, cron = session_identity() or self._fallback_key, get_session_env("HERMES_CRON_SESSION") == "1"
        target = resolve_target(key, cron, p._default_target, p._registry, p._relay,
                                require_contact=require_contact)
        identity = key, target.device if isinstance(target, OnDevice) else "server"
        with self._lock:
            return self._select(identity, target)

    def _create(self, target, key, cwd):
        if isinstance(target, OnDevice):
            require_online(target.device, self._provider._relay)
            return DirtsideEnvironment(self._provider._relay, target.device, key, self._task_id, cwd, self._timeout)
        return LocalEnvironment(cwd=cwd, timeout=self._timeout)

    def _select(self, identity, target):
        from tools.terminal_tool import get_session_cwd, record_session_cwd
        p = self._provider
        with p._lock:
            state = p._state(identity[0], self._cwd)
            cwd = state["cwds"].get(identity, "~")
            if state["identity"] == identity:
                cwd = get_session_cwd(identity[0]) or cwd
        existing = identity in self._environments
        if not existing:
            self._environments[identity] = self._create(target, identity[0], cwd)
        env = self._environments[identity]
        with p._lock:
            state = p._state(identity[0], self._cwd)
            previous, cwds = state["identity"], state["cwds"]
            if previous != identity:
                if previous:
                    cwds[previous] = get_session_cwd(previous[0]) or cwds[previous]
                elif existing:
                    cwds[identity] = env.cwd
                record_session_cwd(identity[0], cwds.setdefault(identity, env.cwd))
                state["identity"] = identity
            p._conversations[identity[0]] = self
        self._last = env
        return env

    def get_temp_dir(self):
        return self._current().get_temp_dir()

    def __getattr__(self, name):
        # Unknown probes must stay registry-free.
        getattr(self.__dict__.get("_last"), name)
        return getattr(self._current(name == "execute"), name)

    @property
    def cwd(self):
        try:
            return self._current().cwd
        except EnvironmentConnectionError:
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
        self._conversations = weakref.WeakValueDictionary()
        self._states, self._lock = {}, threading.RLock()

    def _state(self, key, cwd):
        state = self._states.pop(key, None)
        if state is None:
            state = {"identity": None, "cwds": {(key, "server"): cwd or "~"}}
        self._states[key] = state
        if len(self._states) > 1024:
            del self._states[next(iter(self._states))]
        return state

    @property
    def default_cwd(self):
        env = self._conversations.get(session_identity())
        if env is not None:
            env._current()
        return "~"

    def is_available(self):
        return True

    def create_environment(self, *, cwd, timeout, task_id="default", image=None,
                           container_config=None, **kwargs):
        return ConversationEnvironment(self, session_identity(), cwd, timeout, task_id)
