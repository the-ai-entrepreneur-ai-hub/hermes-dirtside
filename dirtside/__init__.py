"""Provider registration for the in-process plugin."""
from plugins.plugin_storage import plugin_data_dir


def register(ctx):
    from .access import Access
    from .auth import DirtsideDeviceAuth, register_device_routes
    from .backend import tool_execution
    from .cli import handle, setup_parser
    from .client import Client
    from .commands import Commands
    from .prompt import TargetPrompt
    from .provider import DirtsideProvider
    from .registry import Registry
    from .relay import Relay

    registry = Registry(plugin_data_dir("dirtside") / "data.db")
    relay = Relay(registry)
    access = relay.access = Access(ctx)
    relay._client = Client(relay)
    default = ctx.get_config("default_target", "server") or "server"
    ctx.register_terminal_environment_provider(
        DirtsideProvider(registry, relay, default, access))
    ctx.register_middleware("tool_execution", tool_execution)
    ctx.register_dashboard_auth_provider(DirtsideDeviceAuth(registry, relay, default))
    register_device_routes()
    ctx.register_cli_command("dirtside", "Pair and run a personal device", setup_parser, handle)
    ctx.register_command("dirtside", Commands(ctx, registry, relay, default, access),
                         description="Choose a personal device", args_hint="<use|devices|pair|revoke>",
                         argument_mode="text")
    ctx.register_system_prompt_section("dirtside.target", TargetPrompt(registry, relay, default, access).current_target_section,
                                      position="after_memory", max_chars=600)
