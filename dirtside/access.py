"""Current-turn sender authority, independent of conversation target selection."""
import re

from gateway.session_context import get_session_env

from .environment import EnvironmentConnectionError

_LOCAL = {"cli", "tui", "desktop", "acp"}
_UNSET = object()


def valid_sender(value):
    return type(value) is str and (value == "local" or bool(re.fullmatch(
        r"[a-z][a-z0-9_-]{0,31}:[^\s\x00-\x1f\x7f-\x9f]{1,256}", value))
        and value.isprintable())


class Access:
    def __init__(self, ctx=None, *, owners=_UNSET):
        self.ctx = ctx
        if owners is _UNSET:
            owners = ctx.get_config("owners", []) if ctx is not None else []
        if type(owners) is not list or len(owners) > 64 or not all(valid_sender(o) for o in owners):
            raise ValueError("owners must be a list of at most 64 local or platform:user identities")
        if len(set(owners)) != len(owners):
            raise ValueError("owners must not contain duplicate identities")
        self.owners = tuple(owners)

    def identity(self):
        if self.ctx is None:
            return "local"  # Direct Python callers are host-owned, not chat entry points.
        platform = get_session_env("HERMES_SESSION_PLATFORM")
        user = get_session_env("HERMES_SESSION_USER_ID")
        surface, source = self.ctx.session_surface(), get_session_env("HERMES_SESSION_SOURCE")
        if platform == "local" and surface in _LOCAL:
            return "local"
        if not user and platform in ("", "cron") and get_session_env("HERMES_CRON_SESSION") == "1":
            return "local"
        if not user and self._local(surface, platform, source):
            return "local"
        identity = f"{platform}:{user}" if platform and user else ""
        return identity if valid_sender(identity) else ""

    def _local(self, surface, platform, source):
        if surface in _LOCAL:
            return platform in ("", "local", surface)
        return not surface and not platform and source in (_LOCAL | {"gui"})

    def privileged(self, sender):
        return sender == "local" or sender in self.owners

    def allowed(self, owner, sender=None):
        sender = self.identity() if sender is None else sender
        return valid_sender(sender) and (self.privileged(sender) or sender == owner)

    def can(self, device, sender=None):
        return device is not None and self.allowed(device.owner, sender)

    def require(self, device, sender=None):
        sender = self.identity() if sender is None else sender
        if not valid_sender(sender) or not (self.privileged(sender) or self.can(device, sender)):
            raise EnvironmentConnectionError(
                "Dirtside: device is unavailable for this sender. Nothing was run on the server.",
                retry_hint="Run /dirtside use server, or ask the device owner.")

    def may_pair(self):
        sender = self.identity()
        return bool(sender) and (not self.owners or self.privileged(sender))

    def name_allowed(self, registry, name):
        return all(self.allowed(owner) for owner in registry.owners_for_name(name))
