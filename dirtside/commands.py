"""User-only conversation controls, bound to the registered runtime."""
import time

from .provider import session_identity

USAGE = "Use /dirtside, /dirtside use <name|server>, /dirtside devices, /dirtside pair <name>, or /dirtside revoke <name>."

class Commands:
    def __init__(self, ctx, registry, relay, default_target="server"):
        self.ctx, self.registry, self.relay, self.default_target = ctx, registry, relay, default_target

    def __call__(self, raw_args: str) -> str:
        parts = raw_args.split()
        if not parts:
            return self.status()
        handlers = dict(use=self.use, devices=self.devices, pair=self.pair, revoke=self.revoke)
        if len(parts) > 2 or parts[0] not in handlers:
            return USAGE
        try:
            return handlers[parts[0]](parts[1] if len(parts) == 2 else "")
        except ValueError as exc:
            return str(exc).rstrip(".") + "."

    def status(self):
        key = session_identity()
        chosen = self.registry.target(key) if key else None
        default = self.registry.active_device(self.default_target) if self.default_target != "server" else None
        device = self.registry.device_by_id(chosen) if chosen else default
        name = self.label(device) if device else ("an unpaired device" if chosen not in (None, "server") else "server")
        online = ", ".join(d.name for d in self.registry.devices() if self.relay.is_online(d.id)) or "none"
        return f"This conversation targets {name}. Online devices: {online}."

    def label(self, device):
        state = "online" if self.relay.is_online(device.id) else "offline"
        return f"{device.name} ({device.os}, {state})"

    def devices(self, argument):
        if argument:
            return USAGE
        names = "; ".join(self.label(d) for d in self.registry.devices())
        return f"Paired devices: {names}." if names else "No devices are paired."

    def use(self, name):
        key = session_identity()
        if not key:
            return "No conversation is bound; the target was not changed."
        if not name:
            choices = [d.name for d in self.registry.devices() if self.relay.is_online(d.id)] + ["server"]
            name = self.ctx.ask_choice("Where should this conversation run commands?", choices)
            if name is None:
                return "No target was changed."
            if name not in choices:
                return "The choice was not offered; the target was not changed."
        device = self.registry.active_device(name) if name != "server" else None
        if name != "server" and device is None:
            return f"Device '{name}' is not paired; the target was not changed."
        self.registry.set_target(key, device.id if device else "server")
        label = self.label(device) if device else "server"
        return f"This conversation now targets {label}. The change applies to this conversation from the next command."

    def pair(self, name):
        code = self.registry.mint(name, int(time.time()))
        return (f"Pairing code {code} expires in 10 minutes. On the device run: "
                f"hermes dirtside pair <gateway-url> --name {name} --code={code}")

    def revoke(self, name):
        if not name:
            return USAGE
        device = self.registry.revoke(name, int(time.time()))
        if device:
            self.relay.revoke(device.id)
            return f"Revoked {name} and cancelled its live requests."
        return f"No paired device named '{name}' was found; any pending pairing code was revoked."
