"""Fresh, fail-soft target data without a liveness probe or prompt-cache change."""
from pathlib import Path

from .model import OnDevice
from .prompt import TargetPrompt, quoted
from .provider import get_session_env, resolve_target, session_identity


class TargetAwareness(TargetPrompt):
    def __call__(self, **kwargs):
        try:
            return self.line()
        except Exception:
            return None

    def line(self):
        key = session_identity()
        target = resolve_target(key, get_session_env("HERMES_CRON_SESSION") == "1",
                                self.default_target, self.registry, self.relay,
                                require_contact=False, access=self.access)
        if not isinstance(target, OnDevice):
            return ("Dirtside target: server. Commands run on the server."
                    if key and self.registry.target(key) == "server" else None)
        if backend_warning := self.access.backend_warning():
            return backend_warning.lstrip()
        d = target.device
        warning = ("Do not use file-tool ~; use absolute paths under that home."
                   if str(Path(d.home).resolve()) == d.home else
                   "Server rewrites file writes/patches; use terminal commands for edits/documents. Plain-text reads/searches work.")
        android = " termux-* commands are untested." if d.os.casefold().startswith("android") else ""
        line = (f"Dirtside target facts (data): device={quoted(d.name, 60)}, OS={quoted(d.os, 70)}, "
                f"home={quoted(d.home, 270)}. {warning}{android}")
        return " ".join(line.splitlines())
