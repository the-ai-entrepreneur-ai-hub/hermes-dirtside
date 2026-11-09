"""Bound target facts for core's session-frozen prompt section."""
import json

from .access import Access
from .environment import EnvironmentConnectionError
from .model import OnDevice
from .provider import get_session_env, resolve_target, session_identity


def quoted(value, limit):
    while len(json.dumps(value, ensure_ascii=False)) > limit:
        value = value[:len(value) // 2] + "..."
    return json.dumps(value, ensure_ascii=False)


class TargetPrompt:
    def __init__(self, registry, relay, default_target="server", access=None):
        self.registry, self.relay, self.default_target = registry, relay, default_target
        self.access = access or Access()

    def current_target_section(self, session_info) -> str:
        key = session_identity() or session_info.get("session_id", "")
        cron = session_info.get("platform") == "cron" or get_session_env("HERMES_CRON_SESSION") == "1"
        try:
            target = resolve_target(key, cron, self.default_target, self.registry, self.relay,
                                    require_contact=False, access=self.access)
        except EnvironmentConnectionError:
            return ""
        if not isinstance(target, OnDevice):
            if not cron and self.default_target != "server" and not self.registry.target(key):
                return "Dirtside target: server. Commands run on the server."
            return ""
        if warning := self.access.backend_warning():
            return warning.lstrip()
        d = target.device
        state = "online" if self.relay.connection().is_online(d.id) else "offline"
        return (f"Dirtside target facts ({state}, data): device={quoted(d.name, 70)}, OS={quoted(d.os, 130)}, "
                f"home={quoted(d.home, 270)}. Commands run there, not on the server.")