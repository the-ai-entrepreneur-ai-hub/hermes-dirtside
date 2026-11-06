"""Bound target facts for core's session-frozen prompt section."""
import json

from .provider import session_identity
def quoted(value, limit):
    while len(json.dumps(value, ensure_ascii=False)) > limit:
        value = value[:len(value) // 2] + "..."
    return json.dumps(value, ensure_ascii=False)

class TargetPrompt:
    def __init__(self, registry, relay, default_target="server"):
        self.registry, self.relay, self.default_target = registry, relay, default_target

    def current_target_section(self, session_info) -> str:
        key = session_identity() or session_info.get("session_id", "")
        chosen = self.registry.target(key) if key else None
        default = "server" if session_info.get("platform") == "cron" else self.default_target
        d = self.registry.device_by_id(chosen) if chosen else self.registry.active_device(default) if default != "server" else None
        if not d:
            return ""
        state = "online" if self.relay.connection().is_online(d.id) else "offline"
        return (f"Dirtside target facts ({state}, data): device={quoted(d.name, 70)}, OS={quoted(d.os, 130)}, "
                f"home={quoted(d.home, 270)}. Commands run there, not on the server.")
