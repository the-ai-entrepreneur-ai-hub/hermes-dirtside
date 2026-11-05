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
    def __init__(self, port):
        from hermes_cli.plugins import get_plugin_manager
        self.manager = get_plugin_manager()
        self.manager.discover_and_load()
        from hermes_cli.dashboard_auth import get_provider
        self.auth = get_provider("dirtside")
        assert self.auth is not None, self.manager.list_plugins()
        from hermes_cli import web_server
        self.web = web_server
        web_server._configure_auth_gate("127.0.0.1", False, None, None)
        assert web_server.app.state.auth_required
        self.blocked = threading.Event()
        self.active, self.lock = {}, threading.Lock()
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
                    backend=_get_env_config()["env_type"], gate=self.web.app.state.auth_required, port=self.port)

    def target(self, args):
        device = self.auth.registry.active_device(args["name"]) if args["name"] != "server" else None
        assert device is not None or args["name"] == "server", "device is not paired"
        self.auth.registry.set_target(args["session"], device.id if device else None)
        return {}

    def state(self, args):
        from tools.terminal_tool import _resolve_container_task_id
        from tools.terminal_tool_lifecycle import get_active_env, is_persistent_env
        task = args.get("task_id", args["session"])
        env = get_active_env(task)
        return dict(key=_resolve_container_task_id(task), identity=id(env) if env else None,
                    environment=type(env).__name__, cwd=env.cwd if env else None,
                    persistent=is_persistent_env(task))

    def turn_end(self, args):
        from agent.chat_completion_helpers import cleanup_task_resources
        cleanup_task_resources(SimpleNamespace(verbose_logging=False), args.get("task_id", args["session"]))
        return self.state(args)

    def reap(self, args):
        from tools.terminal_tool_lifecycle import _cleanup_inactive_envs
        _cleanup_inactive_envs(lifetime_seconds=0)
        return self.state(args)

    def terminal(self, args):
        from tools.terminal_tool import terminal_tool
        return json.loads(terminal_tool(task_id=args.get("task_id", args["session"]), **args["args"]))

    def file(self, args):
        from tools.file_tools import patch_tool, read_file_tool, search_tool, write_file_tool
        fn = dict(read_file=read_file_tool, write_file=write_file_tool, patch=patch_tool, search_files=search_tool)
        return json.loads(fn[args["tool"]](task_id=args.get("task_id", args["session"]), **args["args"]))

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

    def network(self, args):
        (self.blocked.set if args["blocked"] else self.blocked.clear)()
        return {}

    def dispatch(self, message):
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools.interrupt import set_interrupt
        args = message.get("params", {})
        session = args.get("session", "integration")
        args = {"session": session, **args}
        tokens = set_session_vars(session_key=session, session_id=session, source="cli",
                                  cron_session=args.get("cron", ""))
        with self.lock:
            self.active[message["id"]] = threading.get_ident()
        try:
            handlers = {name: getattr(self, name) for name in (
                "info", "target", "state", "turn_end", "reap", "terminal", "file",
                "queue", "cancel", "interrupt", "network")}
            return handlers[message["method"]](args)
        finally:
            set_interrupt(False)
            clear_session_vars(tokens)
            with self.lock:
                self.active.pop(message["id"], None)

    def close(self):
        from tools.terminal_tool_lifecycle import cleanup_all_environments
        for device in self.auth.registry.devices():
            self.auth.relay.revoke(device.id)
        self.server.should_exit = True
        self.thread.join(6)
        self.listener.close()
        assert not self.thread.is_alive(), "dashboard did not stop"
        sys.modules["hermes_dashboard_plugin_dirtside"].POLL_POOL.shutdown(wait=True)
        cleanup_all_environments()
        self.manager.unload()


def main():
    output, sys.stdout = sys.stdout, sys.stderr
    lock = threading.Lock()
    def emit(value):
        with lock:
            output.write(json.dumps(value) + "\n")
            output.flush()
    runtime = Runtime(int(sys.argv[1]))
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
