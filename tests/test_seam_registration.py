"""Missing public method and route-dependent replies, with real success controls."""
import argparse

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_cli.dashboard_auth import token_auth
from network_support import mounted
from route_support import MissingMethodContext, plugin_context, record_routes, register
from test_review_token_routes import closed_responses

from dirtside import cli
from dirtside.access import Access
from dirtside.commands import Commands


@pytest.mark.parametrize("unavailable", ["missing", "noncallable"])
@pytest.mark.parametrize("gate", [False, True])
def test_unavailable_method_closes_every_route(tmp_path, monkeypatch, caplog, unavailable, gate):
    calls, real = [], token_auth.register_token_route
    def private(path):
        calls.append(path)
        return real(path)
    monkeypatch.setattr(token_auth, "register_token_route", private)
    with plugin_context() as ctx:
        negative = MissingMethodContext(ctx)
        if unavailable == "noncallable":
            negative.register_dashboard_token_route = None
        provider = register(negative, tmp_path, monkeypatch)
        assert not provider.routes.enabled
        assert calls == []
        assert all(status == 401 for _, _, status in closed_responses(provider, tmp_path, gate))
        warnings = [r.getMessage() for r in caplog.records if r.name == "dirtside.auth"]
        assert len(warnings) == 1 and len(warnings[0]) < 160
        assert warnings[0] == provider.routes.reason
        assert "Hermes" in warnings[0] and "register_dashboard_token_route" in warnings[0]
        assert "older" in warnings[0] or "old" in warnings[0]
        ctx._manager.unload()
        good = register(ctx, tmp_path, monkeypatch)
        assert good.routes.enabled and not good.routes.reason
        with mounted(tmp_path, relay=good.relay, provider=good) as (app, *_), TestClient(app, client=("127.0.0.1", 10)) as web:
            assert web.get("/api/plugins/dirtside/local/devices",
                           headers={"Authorization": "Bearer " + good.registry.local_secret}).status_code == 200


@pytest.mark.parametrize("cause", ["missing", "none", "raise"])
def test_commands_report_current_closure_without_minting(tmp_path, monkeypatch, cause, configured_backend):
    with plugin_context() as ctx:
        tokens = set_session_vars(session_key="telegram:test", session_id="test", platform="telegram", user_id="alice")
        try:
            with monkeypatch.context() as failing:
                registrar = MissingMethodContext(ctx) if cause == "missing" else ctx
                if cause != "missing":
                    record_routes(ctx, failing, 3, cause)
                provider = register(registrar, tmp_path, failing)
                commands = Commands(ctx, provider.registry, provider.relay, access=Access(ctx, owners=["telegram:alice"]))
                changes = provider.registry._connection().total_changes
                reply = commands("pair laptop")
                assert "disabled" in reply and ("Hermes" in reply or "registration" in reply)
                assert {"missing": "register_dashboard_token_route", "none": "refused", "raise": "failed"}[cause] in reply
                assert reply == provider.routes.reason
                assert provider.registry._connection().total_changes == changes
                assert commands("") == provider.routes.reason
                set_session_vars(session_key="telegram:test", session_id="test", platform="telegram", user_id="mallory")
                assert commands("pair laptop") == "Pairing is unavailable for this sender."
                assert commands("") == "This conversation targets server. Online devices: none. Sender: telegram:mallory."
                set_session_vars(session_key="telegram:test", session_id="test", platform="telegram", user_id="alice")
                failing.setattr(commands.access, "may_pair", lambda: False)
                assert commands("pair laptop") == "Pairing is unavailable for this sender."
            ctx._manager.unload()
            good = register(ctx, tmp_path, monkeypatch)
            assert good.routes.enabled
            assert "Pairing code" in Commands(ctx, good.registry, good.relay)("pair laptop")
        finally:
            clear_session_vars(tokens)


@pytest.mark.parametrize("status", [401, 403, 400])
def test_pairing_authentication_hint_is_conditional_and_private(monkeypatch, capsys, status):
    calls, real = [], httpx.Client
    code = "private-pairing-code"
    def answer(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "Rejected " + code}, request=request)
    monkeypatch.setattr(cli.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    monkeypatch.setattr(cli.DeviceConfig, "load", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    parser = argparse.ArgumentParser()
    cli.setup_parser(parser, standalone=True)
    args = parser.parse_args(["pair", "http://127.0.0.1:1", "--name", "laptop", "--code", code])
    assert cli.handle(args) == 1
    output = capsys.readouterr().out
    assert code not in output and "[redacted]" in output
    assert len(calls) == 1
    assert ("register_dashboard_token_route" in output) is (status in {401, 403})
    if status in {401, 403}:
        assert output.splitlines()[1] == (
            "If the gateway lacks ctx.register_dashboard_token_route, upgrade Hermes to open Dirtside routes.")
    assert len(output) < 700 and output.count("\n") == 1 + (status in {401, 403}) and "\x1b" not in output
