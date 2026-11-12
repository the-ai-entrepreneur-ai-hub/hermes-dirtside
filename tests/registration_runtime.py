"""Real loader interventions and observations for registration lifetime tests."""
import os
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from nacl.signing import SigningKey


def targeted(runtime, args):
    from hermes_cli.dashboard_auth import get_provider, token_auth
    from hermes_cli.dashboard_auth import registry
    real, observed = registry.unregister_global_provider, {}
    state = {"armed": False}
    def unregister(name, provider=None):
        if name == "dirtside" and state["armed"]:
            state["armed"] = False
            observed.update(registered=get_provider(name) is provider, enabled=provider.routes.enabled,
                            active=[handle.active for handle in provider.routes.registrations],
                            bound=sum(path.startswith("/api/plugins/dirtside/")
                                      for path in token_auth._token_route_policies))
            with TestClient(runtime.web.app, client=("127.0.0.1", 10)) as web:
                for kind, token in state["tokens"].items():
                    response = web.post("/api/gateway/drain", json={"action": "drain"},
                                        headers={"Authorization": "Bearer " + token})
                    observed[kind] = dict(status=response.status_code,
                                         recognized=provider.verify_token(token=token) is not None)
                    control = web.post("/api/gateway/drain", json={"action": "cancel"},
                                       headers={"Authorization": "Bearer " + os.environ["HERMES_DASHBOARD_DRAIN_SECRET"]})
                    assert control.status_code == 200, control.text
        return real(name, provider)
    registry.unregister_global_provider = unregister
    original_time = time.time
    now = int(original_time())
    time.time = lambda: now
    try:
        runtime.reload({})
        provider = runtime.auth
        root = Path(os.environ["HERMES_SRC"]) / "plugins/dashboard_auth/drain"
        manifest = next(item for item in runtime.manager._scan_directory(root.parent, source="bundled")
                        if Path(item.path) == root)
        runtime.manager._load_plugin(manifest)
        assert get_provider("drain-secret") is not None
        def pair(name):
            key = SigningKey.generate()
            provider.registry.mint(name, now)
            hello = provider.protocol.DeviceHello(bytes(key.verify_key), name, "test", "", "/", "/", "0.1.0")
            return provider.registry.complete_pairing(name, hello, now)
        _, bearer = pair("active")
        retired, retained = pair("retained")
        provider.registry.revoke(retired.name, now)
        state["tokens"] = dict(device=bearer, pair=provider.registry.mint("pending", now),
                               local=provider.registry.local_secret, retained=retained)
        assert all(provider.verify_token(token=token) is not None for token in state["tokens"].values())
        state["armed"] = True
        runtime.manager.unload("dirtside")
        assert observed and not state["armed"]
        observed.update(removed=get_provider("dirtside") is None, closed=not provider.routes.enabled)
        return observed
    finally:
        time.time = original_time
        registry.unregister_global_provider = real


def scenario(runtime, args):
    actions = dict(targeted=targeted, refuse=refuse, state=state, arm=arm, pause=pause, ready=ready,
                   release=release, finish=finish, work=work, worker_ready=worker_ready,
                   worker_send=worker_send, reject=reject)
    return actions[args["action"]](runtime, args)


def state(runtime, args):
    relay = runtime.auth.relay
    return dict(revoked=args["device_id"] in relay._revoked,
                rows={row.id: row.state.value for row in relay.registry.recent(50)})


def refuse(runtime, args):
    from hermes_cli.config import atomic_config_write, load_config
    from hermes_cli.plugins import PluginContext
    from hermes_constants import get_hermes_home
    config = load_config()
    config["plugins"]["entries"]["dirtside"]["settings"]["owners"] = ["telegram:alice"]
    atomic_config_write(get_hermes_home() / "config.yaml", config)
    real, calls = PluginContext.register_dashboard_token_route, []
    def register(ctx, path, *, provider, required_scopes=()):
        if ctx.manifest.name == "dirtside":
            calls.append(path)
            if len(calls) == 5:
                return None
        return real(ctx, path, provider=provider, required_scopes=required_scopes)
    PluginContext.register_dashboard_token_route = register
    try:
        runtime.reload({})
    finally:
        PluginContext.register_dashboard_token_route = real
    assert len(calls) == 5 and not runtime.auth.routes.enabled
    return dict(reason=runtime.auth.routes.reason,
                local_origin=runtime.auth.relay._client.origin(),
                owner_pid=runtime.auth.relay._owner_pid == os.getpid())


def arm(runtime, args):
    window = dict(ready=threading.Event(), release=threading.Event(), rejected=threading.Event(),
                  responses=[], position=args.get("position"), app=runtime.app)
    async def observed(scope, receive, send):
        async def record(message):
            if scope.get("path", "").startswith("/api/plugins/dirtside/local/") and message["type"] == "http.response.start":
                status = message["status"]
                window["responses"].append([scope["path"].rsplit("/", 1)[1], status])
                if status == 401:
                    window["rejected"].set()
            await send(message)
        await window["app"](scope, receive, record)
    runtime.reload_window, runtime.app = window, observed
    return {}


def pause(runtime, args):
    from hermes_cli.plugins import PluginContext
    real, calls = PluginContext.register_dashboard_token_route, []
    window = runtime.reload_window
    def register(ctx, path, *, provider, required_scopes=()):
        if ctx.manifest.name == "dirtside":
            calls.append(path)
            if len(calls) == window["position"]:
                window["ready"].set()
                assert window["release"].wait(10), "reload was not released"
        return real(ctx, path, provider=provider, required_scopes=required_scopes)
    PluginContext.register_dashboard_token_route = register
    try:
        result = runtime.reload({})
        assert len(calls) == 9
        return result
    finally:
        window["release"].set()
        PluginContext.register_dashboard_token_route = real


def ready(runtime, args):
    return runtime.reload_window["ready"].is_set()


def release(runtime, args):
    window = runtime.reload_window
    observed = window["rejected"].wait(5)
    window["release"].set()
    assert observed, "worker did not reach the real closed route"
    return {}


def finish(runtime, args):
    window = runtime.reload_window
    runtime.app = window["app"]
    return window["responses"]


def work(runtime, args):
    if args["stage"] == "devices":
        return runtime.terminal(dict(session=args["session"], args={"command": args["command"]}))
    client = runtime.auth.relay._client
    device = runtime.auth.registry.active_device(args["name"])
    request = runtime.auth.model.ExecRequest(args["request_id"], device.id, args["session"], "worker",
                                             args["command"], args["command"], False, 10, None, device.home)
    events = runtime.worker_window = dict(ready=threading.Event(), send=threading.Event())
    real = client.stream
    def delayed(*values):
        events["ready"].set()
        events["send"].wait(10)
        real(*values)
    if args["stage"] == "stream":
        client.stream = delayed
    try:
        handle = client.submit(request)
        try:
            code = handle.wait(8)
            return dict(exit_code=code, output=handle.stdout.read().decode(), request_id=request.id)
        finally:
            handle.stdout.close()
    finally:
        client.stream = real


def worker_ready(runtime, args):
    return getattr(runtime, "worker_window", {}).get("ready", threading.Event()).is_set()


def worker_send(runtime, args):
    runtime.worker_window["send"].set()
    return {}


def unreachable(*, token):
    from hermes_cli.dashboard_auth import ProviderError
    raise ProviderError("test unavailable")


def reject(runtime, args):
    import secrets
    from dataclasses import asdict
    provider, status = runtime.auth, args["status"]
    client, device = provider.relay._client, provider.registry.active_device(args["name"])
    request = provider.model.ExecRequest("r_" + secrets.token_hex(12), device.id, args["session"], "control",
                                        "printf control", "printf control", False, 10, None, device.home)
    if status == 409:
        handle = client.submit(request)
        try:
            assert handle.wait(8) == 0 and handle.stdout.read() == b"control"
        finally:
            handle.stdout.close()
    data = asdict(request)
    if status == 400:
        data = {}
    if status == 403:
        data["sender"] = "telegram:mallory"
    real = provider.verify_token
    if status == 503:
        provider.verify_token = unreachable
    runtime.reload_window["responses"].clear()
    before = len(provider.registry.recent(50))
    try:
        if status == 410:
            client.request("GET", "/stream", params={"id": request.id})
        else:
            client.request("POST", "/exec", json=data)
    except provider.connection_error as exc:
        message = str(exc)
    else:
        raise AssertionError("local route unexpectedly accepted the request")
    finally:
        provider.verify_token = real
    assert len(provider.registry.recent(50)) == before
    assert client.request("GET", "/devices")
    return message
