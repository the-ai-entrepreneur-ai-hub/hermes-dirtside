"""User-only conversation controls, bound to the registered runtime."""
import time
from .access import Access

from .model import OnDevice
from .provider import NoSingleSenderError, get_session_env, resolve_target, session_identity
from .environment import EnvironmentConnectionError
from .prompt import quoted

USAGE = "Use /dirtside, /dirtside use <name|server>, /dirtside devices, /dirtside pair <name>, or /dirtside revoke <name>."

class Commands:
    def __init__(self, ctx, registry, relay, default_target="server", access=None):
        self.ctx, self.registry, self.relay, self.default_target = ctx, registry, relay, default_target
        self.access = access or Access(ctx if hasattr(ctx, "session_surface") else None)

    def visible(self):
        return [d for d in self.registry.devices() if self.access.can(d)]

    def __call__(self, raw_args: str, *, source=None) -> str:
        token = self.access.command_source.set(source)
        try:
            return self.dispatch(raw_args)
        finally:
            self.access.command_source.reset(token)

    def dispatch(self, raw_args):
        parts = raw_args.split()
        handlers = dict(use=self.use, devices=self.devices, pair=self.pair, revoke=self.revoke)
        if len(parts) > 2 or (parts and parts[0] not in handlers):
            return USAGE
        try:
            if not parts:
                return self.status()
            return handlers[parts[0]](parts[1] if len(parts) == 2 else "")
        except ValueError as exc:
            return str(exc).rstrip(".") + "."
        except EnvironmentConnectionError as exc:
            return str(exc)

    def status(self):
        try:
            target = resolve_target(session_identity(), get_session_env("HERMES_CRON_SESSION") == "1",
                                    self.default_target, self.registry, self.relay, require_contact=False, access=self.access)
        except NoSingleSenderError as exc:
            return f"No device applies to a turn without a sender. {exc}"
        except EnvironmentConnectionError:
            target = None
        if self.access.may_pair() and (reason := getattr(self.relay, "_routes_reason", lambda: "")()):
            return reason
        name = self.label(target.device) if isinstance(target, OnDevice) else (
            "an unpaired device" if target is None else "server")
        online = ", ".join(d.name for d in self.visible() if self.relay.connection().is_online(d.id)) or "none"
        return f"This conversation targets {name}. Online devices: {online}. Sender: {self.access.identity() or 'unknown'}."

    def label(self, device):
        state = "online" if self.relay.connection().is_online(device.id) else "offline"
        return f"{device.name} ({device.os}, {state})"

    def devices(self, argument):
        if argument:
            return USAGE
        names = "; ".join(self.label(d) for d in self.visible())
        return f"Paired devices: {names}." if names else "No devices are paired."

    def use(self, name):
        key = session_identity()
        if not key:
            return "No conversation is bound; the target was not changed."
        if not name:
            choices = [d.name for d in self.visible() if self.relay.connection().is_online(d.id)] + ["server"]
            name = self.ctx.ask_choice("Where should this conversation run commands?", choices)
            if name is None:
                return "No target was changed."
            if name not in choices:
                return "The choice was not offered; the target was not changed."
        device = self.registry.active_device(name) if name != "server" else None
        if name != "server" and not self.access.can(device):
            return f"Device '{name}' is not paired; the target was not changed."
        label = self.label(device) if device else "server"
        if device and self.access.privileged(self.access.identity()) and not self.access.privileged(device.owner):
            label += f", owned by {device.owner}"
        self.registry.set_target(key, device.id if device else "server")
        home = f" Home: {quoted(device.home, 270)}." if device else ""
        return f"This conversation now targets {label}.{home} The change applies to this conversation from the next command." + (self.access.backend_warning() if device else "")

    def pair(self, name):
        if not self.access.may_pair() or not self.access.name_allowed(self.registry, name):
            return "Pairing is unavailable for this sender."
        if reason := getattr(self.relay, "_routes_reason", lambda: "")():
            return reason
        sender = self.access.identity()
        code = self.registry.mint(name, int(time.time()), owner=sender, privileged=self.access.privileged(sender))
        return (f"Pairing code {code} expires in 10 minutes. Without Hermes run: "
                f"dirtside-agent pair <gateway-url> --name {name} --code={code}\nOn the device run: "
                f"hermes dirtside pair <gateway-url> --name {name} --code={code}")

    def revoke(self, name):
        if not name:
            return USAGE
        device = (self.registry.revoke(name, int(time.time()), owner=self.access.identity(),
                                       privileged=self.access.privileged(self.access.identity()))
                  if self.access.name_allowed(self.registry, name) else None)
        if device:
            self.relay.connection().revoke(device.id)
            return f"Revoked {name} and cancelled its live requests."
        return f"No paired device named '{name}' was found; any pending pairing code was revoked."
