"""Private stdio-driven core process for integration tests and the owned matrix rig."""
import json
import signal
import socket
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import uvicorn
from starlette.responses import JSONResponse


class Runtime:
    def __init__(self, port, worker=False):
        from hermes_cli.plugins import get_plugin_manager
        self.manager = get_plugin_manager()
        self.manager.discover_and_load()
        from hermes_cli.dashboard_auth import get_provider
        self.auth = get_provider("dirtside")
        assert self.auth is not None, self.manager.list_plugins()
        self.worker, self.fakes = worker, []
        self.active, self.lock, self.prompt_agents = {}, threading.Lock(), {}
        if worker:
            self.port = 0
            return
        from hermes_cli import web_server
        self.web = web_server
        web_server._configure_auth_gate("127.0.0.1", False, None, None)
        assert web_server.app.state.auth_required
        self.blocked = threading.Event()
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.port = self.listener.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(
            self.application, interface="asgi3", log_level="error", lifespan="off", timeout_graceful_shutdown=1))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.listener]}, daemon=True)
        self.thread.start()
        deadline = threading.Event()
        for _ in range(3000):
            if self.server.started:
                break
            assert self.thread.is_alive(), "dashboard listener stopped"
            deadline.wait(0.01)
        assert self.server.started, "dashboard listener did not start"

    async def application(self, scope, receive, send):
        # A transport fault outside the unmodified core app, never a production route.
        if self.blocked.is_set() and scope.get("path", "").startswith("/api/plugins/dirtside/device/"):
            await JSONResponse({"detail": "rig reporting outage"}, status_code=503)(scope, receive, send)
        else:
            await self.web.app(scope, receive, send)

    def info(self, _):
        from agent.terminal_env_registry import get_provider
        from tools.terminal_tool import _get_env_config
        loaded = self.manager._plugins["dirtside"]
        provider = get_provider("dirtside")
        return dict(enabled=loaded.enabled, error=loaded.error, source=loaded.manifest.source,
                    path=str(loaded.manifest.path), module=type(provider).__module__,
                    shared=provider._relay is self.auth.relay and provider._registry is self.auth.registry,
                    auth=type(self.auth).__name__, cli=sorted(self.manager._cli_commands),
                    backend=_get_env_config()["env_type"], gate=not self.worker and self.web.app.state.auth_required,
                    port=self.port, registry=str(self.auth.registry.path), owner_pid=self.auth.relay._owner_pid,
                    router_mounted="hermes_dashboard_plugin_dirtside" in sys.modules)

    def fake_device(self, args):
        import base64
        from dataclasses import replace
        import httpx
        from fake_device import FakeDevice
        from nacl.signing import SigningKey
        import shlex
        import time
        class HomeDevice(FakeDevice):
            def _execute(self, req, cancel):
                script = "export HOME=" + shlex.quote(self.device.home) + "\n" + req.script
                return super()._execute(replace(req, script=script), cancel)
        key = SigningKey.generate()
        registry, wire = self.auth.registry, self.auth.protocol
        name, root = args.get("name", "fake"), args["root"]
        code = registry.mint(name, int(time.time()), owner=args.get("owner", "local"))
        hello = dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name=name,
                     os=sys.platform, arch="", home=root, temp_dir=root, agent_version="0.1.0")
        url = f"http://127.0.0.1:{self.port}/api/plugins/dirtside/device/"
        response = httpx.post(url + "pair", headers={"Authorization": "Bearer " + code},
                              json=wire.sign(key, "hello", name, hello), trust_env=False)
        response.raise_for_status()
        device, token = registry.active_device(name), response.json()["token"]
        try:
            httpx.post(url + "poll", headers={"Authorization": "Bearer " + token},
                       json=wire.sign(key, "poll", device.id, {}), timeout=0.2, trust_env=False)
        except httpx.ReadTimeout:
            pass  # Exercise a real device poll, then release its parked request.
        assert self.auth.relay.is_online(device.id)
        fake = HomeDevice(self.auth.relay, device, token, key, result_parser=wire.parse_result)
        fake.__enter__()
        self.fakes.append(fake)
        return {"device_id": device.id, "name": name}

    def target(self, args):
        device = self.auth.registry.active_device(args["name"]) if args["name"] != "server" else None
        assert device is not None or args["name"] == "server", "device is not paired"
        self.auth.registry.set_target(args["session"], device.id if device else "server")
        return {}

    def slash(self, args):
        from hermes_cli.plugin_command_dispatch import invoke_plugin_command
        name = args.get("command", "dirtside")
        command = self.manager._plugin_commands[name]
        assert command["argument_mode"] == "text"
        assert name != "dirtside" or command["args_hint"] == "<use|devices|pair|revoke>"
        if "choice" not in args:
            return invoke_plugin_command(command["handler"], args["raw_args"])
        handler = command["handler"]
        commands = handler if name == "dirtside" else handler.__self__.commands
        original, questions = commands.ctx.ask_choice, []
        def choose(question, choices):
            questions.append([question, choices])
            return args["choice"]
        commands.ctx.ask_choice = choose
        try:
            reply = invoke_plugin_command(handler, args["raw_args"])
            return dict(reply=reply, questions=questions)
        finally:
            commands.ctx.ask_choice = original

    def prompt(self, args):
        from agent.system_prompt import _frozen_plugin_prompt_sections
        agent = self.prompt_agents.setdefault(args.get("snapshot", args["session"]),
                    SimpleNamespace(session_id=args["session"], platform="telegram", model="", provider=""))
        section = self.manager._system_prompt_sections["dirtside.target"]
        assert section.position == "after_memory" and section.max_chars == 600
        return [section.content for section in _frozen_plugin_prompt_sections(agent)
                if section.id == "dirtside.target"]

    def state(self, args):
        from tools.terminal_tool import _resolve_container_task_id
        from tools.terminal_tool_lifecycle import get_active_env, is_persistent_env
        task = args.get("task_id", args["session"])
        env = get_active_env(task)
        return dict(key=_resolve_container_task_id(task), identity=id(env) if env else None,
                    environment=type(env).__name__, cwd=env.cwd if env else None,
                    persistent=is_persistent_env(task))

    def turn_facts(self, args):
        return self.manager.invoke_hook(
            "pre_llm_call", session_id=args["session"], task_id=args["session"], turn_id="rig-turn",
            user_message="next", conversation_history=[{"role": "user", "content": "next"}],
            is_first_turn=False, model="", platform=args.get("platform", "cli"),
            parent_session_id="", sender_id=args.get("user_id", ""))

    def turn_end(self, args):
        from agent.chat_completion_helpers import cleanup_task_resources
        cleanup_task_resources(SimpleNamespace(verbose_logging=False), args.get("task_id", args["session"]))
        return self.state(args)

    def reap(self, args):
        from tools.terminal_tool_lifecycle import _cleanup_inactive_envs
        _cleanup_inactive_envs(lifetime_seconds=0)
        return self.state(args)

    def terminal(self, args):
        from hermes_cli.middleware import run_tool_execution_middleware
        from tools.terminal_tool import terminal_tool
        result = run_tool_execution_middleware("terminal", args["args"],
            lambda payload: terminal_tool(task_id=args.get("task_id", args["session"]), **payload))
        return json.loads(result)

    def file(self, args):
        from hermes_cli.middleware import run_tool_execution_middleware
        from tools.file_tools import patch_tool, read_file_tool, search_tool, write_file_tool
        fn = dict(read_file=read_file_tool, write_file=write_file_tool, patch=patch_tool, search_files=search_tool)
        result = run_tool_execution_middleware(args["tool"], args["args"],
            lambda payload: fn[args["tool"]](task_id=args.get("task_id", args["session"]), **payload))
        return json.loads(result)

    def queue(self, args):
        import secrets
        m = self.auth.model
        device = self.auth.registry.active_device(args["name"])
        req = m.ExecRequest("r_" + secrets.token_hex(12), device.id, args["session"], args["session"],
                            args.get("command", "printf route"), args.get("script", "printf route"),
                            False, 120, None, device.home)
        self.auth.relay.submit(req)
        return {"id": req.id}

    def cancel(self, args):
        self.auth.relay.kill(args["request_id"])
        return {}

    def interrupt(self, args):
        from tools.interrupt import set_interrupt
        with self.lock:
            tid = self.active.get(args["call_id"])
        assert tid is not None, "tool call is not active"
        set_interrupt(True, tid)
        return {}

    def reload(self, args):
        from hermes_cli.dashboard_auth import get_provider
        if "enabled" in args or "default_target" in args:
            from hermes_cli.config import atomic_config_write, load_config
            from hermes_constants import get_hermes_home
            config = load_config()
            if "enabled" in args:
                config["plugins"]["enabled"] = ["dirtside"] if args["enabled"] else []
                config["plugins"]["disabled"] = [] if args["enabled"] else ["dirtside"]
            if "default_target" in args:
                config["plugins"]["entries"]["dirtside"]["settings"]["default_target"] = args["default_target"]
            atomic_config_write(get_hermes_home() / "config.yaml", config)
        previous = self.auth
        self.manager.discover_and_load(force=True)
        current = get_provider("dirtside")
        if current is not None:
            self.auth = current
        return dict(replaced=current is not previous, old_enabled=previous.routes.enabled,
                    enabled=current is not None and current.routes.enabled)

    def stream_attached(self, args):
        relay = self.auth.relay
        with relay._condition:
            return args["request_id"] in relay.handles and args["request_id"] not in relay._streams

    def actor_sequence(self, args):
        from actor_context import sequence
        return sequence(self, args)

    def actor_loop(self, args):
        from actor_loop import run
        return run(self, args)

    def network(self, args):
        (self.blocked.set if args["blocked"] else self.blocked.clear)()
        return {}

    def generation(self, args):
        api = sys.modules["hermes_dashboard_plugin_dirtside"]
        mounted = next(route.endpoint.__self__ for route in api.router.routes
                       if getattr(route.endpoint, "__self__", None) is not None)
        types = type(mounted).output.__globals__
        outcome = types["Outcome"](types["RequestState"].LOST, 255, 0, False, "test mounted generation")
        self.auth.relay.close("r_" + "0" * 24, outcome)
        return {"close": True}

    def dispatch(self, message):
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools.interrupt import set_interrupt
        args = message.get("params", {})
        session = args.get("session", "integration")
        args = {"session": session, **args}
        tokens = set_session_vars(session_key=session, session_id=session, source=args.get("source", "cli"),
                                  platform=args.get("platform", ""), user_id=args.get("user_id", ""),
                                  cron_session=args.get("cron", ""))
        with self.lock:
            self.active[message["id"]] = threading.get_ident()
        try:
            handlers = {name: getattr(self, name) for name in (
                "info", "target", "state", "turn_end", "reap", "terminal", "file",
                "queue", "cancel", "interrupt", "network", "slash", "prompt", "fake_device", "reload", "generation",
                "stream_attached", "turn_facts", "actor_sequence", "actor_loop")}
            return handlers[message["method"]](args)
        finally:
            set_interrupt(False)
            clear_session_vars(tokens)
            with self.lock:
                self.active.pop(message["id"], None)

    def close(self):
        from tools.terminal_tool_lifecycle import cleanup_all_environments
        if self.worker:
            cleanup_all_environments()
            self.manager.unload()
            return
        for fake in self.fakes:
            fake.__exit__(None, None, None)
        for device in self.auth.registry.devices():
            self.auth.relay.revoke(device.id)
        self.server.should_exit = True
        self.thread.join(6)
        self.listener.close()
        assert not self.thread.is_alive(), "dashboard did not stop"
        sys.modules["hermes_dashboard_plugin_dirtside"].POLL_POOL.shutdown(wait=True)
        sys.modules["hermes_dashboard_plugin_dirtside"].FEED_POOL.shutdown(wait=True)
        cleanup_all_environments()
        self.manager.unload()


def main():
    output, sys.stdout = sys.stdout, sys.stderr
    lock = threading.Lock()
    def emit(value):
        with lock:
            output.write(json.dumps(value) + "\n")
            output.flush()
    runtime = Runtime(int(sys.argv[1]), worker="--worker" in sys.argv)
    emit({"id": "ready", "result": runtime.info({})})
    def run(message):
        try:
            emit({"id": message["id"], "result": runtime.dispatch(message)})
        except Exception:
            emit({"id": message["id"], "error": traceback.format_exc()})
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        with ThreadPoolExecutor(max_workers=8) as workers:
            try:
                for line in sys.stdin:
                    workers.submit(run, json.loads(line))
            finally:
                runtime.close()
    finally:
        output.close()


if __name__ == "__main__":
    main()
