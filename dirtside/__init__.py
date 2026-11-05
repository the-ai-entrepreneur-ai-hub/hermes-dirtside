"""Provider registration for the in-process plugin."""
import time

from plugins.plugin_storage import plugin_data_dir


def register(ctx):
    from .provider import DirtsideProvider
    from .registry import Registry
    from .relay import Relay

    registry = Registry(plugin_data_dir("dirtside") / "data.db")
    registry.mark_stale_lost(int(time.time()))
    relay = Relay(registry)
    ctx.register_terminal_environment_provider(
        DirtsideProvider(registry, relay, ctx.get_config("default_target", "server")))
