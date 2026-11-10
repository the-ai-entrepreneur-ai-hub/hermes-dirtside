"""Provider registration for the in-process plugin."""


def register(ctx):
    from hermes_cli.dashboard_auth import get_provider
    from plugins.plugin_storage import plugin_data_dir
    from .access import Access
    from .auth import DirtsideDeviceAuth, register_device_routes
    from .awareness import TargetAwareness
    from .backend import tool_execution
    from .cli import handle, setup_parser
    from .client import Client
    from .commands import Commands
    from .prompt import TargetPrompt
    from .provider import DirtsideProvider
    from .registry import Registry
    from .relay import Relay
    from .shortcuts import Shortcuts

    path, access = plugin_data_dir("dirtside") / "data.db", Access(ctx)
    default = ctx.get_config("default_target", "server") or "server"
    previous = get_provider("dirtside")
    compatible = getattr(previous, "runtime_version", None) == 2 and previous.registry.path == path
    if compatible and previous.routes.enabled:
        return
    if compatible:
        registry, relay, provider, tool_execution = (
            previous.registry, previous.relay, previous.environment_provider, previous.tool_execution)
        relay.access.ctx, relay.access.owners = access.ctx, access.owners
        access, provider._default_target = relay.access, default
    else:
        registry = Registry(path)
        relay = Relay(registry)
        relay.access, relay._client = access, Client(relay)
        provider = DirtsideProvider(registry, relay, default, access)
    ctx.register_terminal_environment_provider(provider)
    ctx.register_middleware("tool_execution", tool_execution)
    auth = DirtsideDeviceAuth(registry, relay, default)
    if compatible:
        # Keep runtime types with live handles when core reloads the package namespace.
        auth.model, auth.protocol = previous.model, previous.protocol
        auth.local = type(previous.local)(registry, relay, lambda: auth.routes.enabled)
    auth.environment_provider, auth.tool_execution = provider, tool_execution
    auth.runtime_version = 2
    if ctx.register_dashboard_auth_provider(auth) is not None:
        auth.routes = register_device_routes(ctx)
    relay._routes_enabled = lambda: auth.routes.enabled
    relay._routes_reason = lambda: auth.routes.reason
    ctx.register_cli_command("dirtside", "Pair and run a personal device", setup_parser, handle)
    ctx.register_hook("pre_llm_call", TargetAwareness(registry, relay, default, access))
    commands = Commands(ctx, registry, relay, default, access)
    ctx.register_command("dirtside", commands,
                         description="Choose a personal device", args_hint="<use|devices|pair|revoke>",
                         argument_mode="text")
    shortcuts = Shortcuts(commands)
    ctx.register_command("land", shortcuts.land, description="Choose a personal device",
                         args_hint="[name|server]", argument_mode="text")
    ctx.register_command("orbit", shortcuts.orbit, description="Run commands on the server",
                         argument_mode="text")
    ctx.register_system_prompt_section("dirtside.target", TargetPrompt(registry, relay, default, access).current_target_section,
                                      position="after_memory", max_chars=600)
