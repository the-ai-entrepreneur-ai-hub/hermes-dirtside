"""One ten-second window from the first revoke or replacement, under either registration API."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hermes_cli.dashboard_auth.registry import register_global_provider
from nacl.signing import SigningKey
from network_support import DESKTOP_TOKEN, listening, until
from notice_support import Clock, FOREIGN, FOREIGN_TOKEN, active_poll, envelope, gateway, retire
from test_network import setup_agent
from test_registry import paired
from test_revoke_exit import body_for, device_path, explicit, generic, invalid_wire
from test_review_token_routes import PublicContext, register
from test_routes import API, headers, hello

from dirtside.agent.loop import _Agent
from dirtside.protocol import ReplayGuard, parse_hello, verify


def core_generic(response):
    assert response.status_code == 401
    assert response.json() == {"error": "unauthenticated", "detail": "Unauthorized"}


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("replaced", [False, True])
@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
@pytest.mark.parametrize("edge", [0, 9, 10])
def test_window_edges_on_every_route(tmp_path, monkeypatch, public, replaced, kind, edge):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, relay, _, provider), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now - 1)
        assert provider.verify_token(token=token) is not None
        assert web.get(FOREIGN, headers=headers(token)).status_code == 200
        retire(reg, device, tmp_path, clock, replaced)
        clock.advance(min(edge, 9))
        body = body_for(kind, key, tmp_path, device.name)
        explicit(web.post(device_path(kind), headers=headers(token),
                          json=envelope(key, kind, device.id, body)))
        assert web.get(FOREIGN, headers=headers(token)).status_code == 200
        if edge == 10:
            clock.advance()
            core_generic(web.post(device_path(kind), headers=headers(token),
                                  json=envelope(key, kind, device.id, body)))
            assert provider.verify_token(token=token) is None
            assert web.get(FOREIGN, headers=headers(token)).status_code == 401
            assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200
        assert not relay.last_seen and not relay.handles


@pytest.mark.parametrize("replaced", [False, True])
@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
@pytest.mark.parametrize("skew", [-60, 0, 60])
def test_independent_device_clock_gets_notice(tmp_path, monkeypatch, replaced, kind, skew):
    gateway_clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, _, _, provider), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=gateway_clock.now - 1)
        assert provider.verify_token(token=token) is not None
        retire(reg, device, tmp_path, gateway_clock, replaced)
        for delay in (0, 9):
            gateway_clock.advance(delay)
            device_now = gateway_clock.now + skew
            wire = envelope(key, kind, device.id, body_for(kind, key, tmp_path, device.name), device_now)
            assert verify(key.verify_key, wire, gateway_clock.now).ts == device_now
            explicit(web.post(device_path(kind), headers=headers(token), json=wire))


@pytest.mark.parametrize("replaced", [False, True])
@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
def test_retries_each_get_notice_inside_window(tmp_path, monkeypatch, replaced, kind):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, _, _, provider), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now - 1)
        assert provider.verify_token(token=token) is not None
        retire(reg, device, tmp_path, clock, replaced)
        for _ in range(3):
            explicit(web.post(device_path(kind), headers=headers(token),
                              json=envelope(key, kind, device.id, body_for(kind, key, tmp_path, device.name))))
        assert provider.verify_token(token=token) is not None


def test_parked_poll_does_not_consume_later_answers(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, _, _), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now - 1)
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(web.post, device_path("poll"), headers=headers(token),
                                  json=envelope(key, "poll", device.id, {}))
            until(lambda: device.id in relay.last_seen, timeout=5)
            assert web.post(API + f"/devices/{device.name}/revoke",
                            headers=headers(DESKTOP_TOKEN)).status_code == 200
            explicit(pending.result(timeout=5))
        with ThreadPoolExecutor(2) as pool:
            responses = [pool.submit(web.post, device_path(kind), headers=headers(token),
                                     json=envelope(key, kind, device.id, body_for(kind, key, tmp_path)))
                         for kind in ("chunk", "result")]
            for response in responses:
                explicit(response.result(timeout=5))
        explicit(web.post(device_path("poll"), headers=headers(token),
                          json=envelope(key, "poll", device.id, {})))


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("replaced", [False, True])
@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
def test_restart_keeps_window_and_resets_replay_guard(tmp_path, monkeypatch, public, replaced, kind):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, _, _, provider), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now - 1)
        assert provider.verify_token(token=token) is not None
        wire = envelope(key, kind, device.id, body_for(kind, key, tmp_path, device.name), clock.now - 60)
        retire(reg, device, tmp_path, clock, replaced)
        explicit(web.post(device_path(kind), headers=headers(token), json=wire))
        generic(web.post(device_path(kind), headers=headers(token), json=wire))
    clock.advance()
    with gateway(tmp_path, monkeypatch, public) as (app, current, relay, module, _), TestClient(app) as web:
        assert current is not reg and not relay._revoked
        monkeypatch.setattr(module.wire, "GATEWAY_REPLAYS", ReplayGuard())
        explicit(web.post(device_path(kind), headers=headers(token), json=wire))
        clock.advance(8)
        explicit(web.post(device_path(kind), headers=headers(token),
                          json=envelope(key, kind, device.id, body_for(kind, key, tmp_path, device.name))))
        clock.advance()
        core_generic(web.post(device_path(kind), headers=headers(token),
                              json=envelope(key, kind, device.id, body_for(kind, key, tmp_path, device.name))))
        assert not relay.last_seen


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("different_owner", [False, True])
def test_repair_never_reopens_first_revocation_window(tmp_path, monkeypatch, public, different_owner):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, _, _, provider), TestClient(app) as web:
        device, token, _ = paired(reg, tmp_path, now=clock.now - 1)
        assert provider.verify_token(token=token) is not None
        event = clock.now
        reg.revoke(device.name, event)
        clock.advance(9)
        assert provider.verify_token(token=token) is not None
        for now in (event + 10, event + 11, event + 301, event + 86399):
            clock.now = now
            assert provider.verify_token(token=token) is None
            assert web.get(FOREIGN, headers=headers(token)).status_code == 401
        clock.now = event + 86400
        key = SigningKey.generate()
        owner = "telegram:bob" if different_owner else device.owner
        code = reg.mint(device.name, clock.now, owner=owner, privileged=True)
        new, new_token = reg.complete_pairing(device.name, parse_hello(hello(key, tmp_path, device.name)),
                                              clock.now, code=code)
        assert (new.id != device.id) is different_owner
        assert provider.verify_token(token=new_token) is not None
        assert web.get(FOREIGN, headers=headers(new_token)).status_code == 200
        assert reg.credential_for(token, clock.now, include_revoked=True).revoked_at == event
        for offset in range(12):
            clock.now = event + 86400 + offset
            assert provider.verify_token(token=token) is None
            assert web.get(FOREIGN, headers=headers(token)).status_code == 401
            assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200


@pytest.mark.parametrize("refusal", ["raise", "none"])
def test_registration_failure_still_closes_retained_bearer(tmp_path, monkeypatch, refusal):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, _, _, good), TestClient(app) as web:
        device, token, _ = paired(reg, tmp_path, now=clock.now - 1)
        reg.revoke(device.name, clock.now)
        assert good.verify_token(token=token) is not None
        assert web.get(FOREIGN, headers=headers(token)).status_code == 200
        bad = register(PublicContext(3, refusal), tmp_path, monkeypatch)
        register_global_provider(bad)
        assert not bad.routes.enabled and bad.verify_token(token=token) is None
        assert web.get(FOREIGN, headers=headers(token)).status_code == 401
        assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200


@pytest.mark.parametrize("replaced", [False, True])
@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
@pytest.mark.parametrize("fault", ["wrong-signature", "unknown-id", "wrong-kind", "stale", "unsigned", "replay"])
def test_invalid_proof_never_gets_stop_inside_or_after_window(tmp_path, monkeypatch, replaced, kind, fault):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, _, _, provider), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now - 1)
        assert provider.verify_token(token=token) is not None
        retire(reg, device, tmp_path, clock, replaced)
        body = body_for(kind, key, tmp_path, device.name)
        wire = invalid_wire(kind, key, device.id, body, fault)
        if fault == "replay":
            explicit(web.post(device_path(kind), headers=headers(token), json=wire))
        generic(web.post(device_path(kind), headers=headers(token), json=wire))
        explicit(web.post(device_path(kind), headers=headers(token),
                          json=envelope(key, kind, device.id, body)))
        clock.advance(10)
        core_generic(web.post(device_path(kind), headers=headers(token), json=wire))
        assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("delay", [0, 9, 10])
@pytest.mark.parametrize("skew", [-60, 0, 60])
def test_real_poll_loop_stops_between_polls_only_inside_window(tmp_path, monkeypatch, public, delay, skew):
    clock = Clock(monkeypatch)
    monkeypatch.setattr("dirtside.agent.loop.sign", lambda key, kind, sender, body:
                        envelope(key, kind, sender, body, clock.now + skew))
    with gateway(tmp_path, monkeypatch, public) as (app, reg, relay, _, _), listening(app) as url:
        device, cfg = setup_agent(reg, tmp_path, url)
        relay.cancels[device.id].add("r_" + "ab" * 12)
        responses, events, stop = [], [], threading.Event()
        def observe(response):
            response.read()
            responses.append((response.status_code, response.json()))
            if len(responses) == 1:
                assert response.status_code == 200
                reg.revoke(device.name, clock.now)
                clock.advance(delay)
        with httpx.Client(base_url=url + "/", headers=headers(cfg.token), trust_env=False,
                          event_hooks={"response": [observe]}) as client:
            agent = _Agent(cfg, client, stop, SimpleNamespace(write=lambda event, **_: events.append(event)))
            thread = threading.Thread(target=agent.poll, daemon=True)
            thread.start()
            try:
                if delay < 10:
                    thread.join(5)
                    assert not thread.is_alive() and stop.is_set()
                    assert responses[1:] == [(401, {"detail": "device revoked"})]
                    assert events == ["contact", "revoked"]
                else:
                    until(lambda: len(responses) >= 4, timeout=5)
                    assert thread.is_alive() and not stop.is_set() and "revoked" not in events
                    assert all(status == 401 and body == {"error": "unauthenticated", "detail": "Unauthorized"}
                               for status, body in responses[1:])
            finally:
                agent.shutdown()
                thread.join(5)
                agent.pool.shutdown(wait=True)
            assert not thread.is_alive()


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
def test_different_owner_http_pair_starts_displaced_window(tmp_path, monkeypatch, public, kind):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, relay, _, provider), TestClient(app) as web:
        old, token, key = paired(reg, tmp_path, now=clock.now - 1)
        active_poll(web, relay, old, token, key)
        event, replacement_key = clock.now, SigningKey.generate()
        code = reg.mint(old.name, event, owner="telegram:bob", privileged=True)
        response = web.post(device_path("hello"), headers=headers(code),
                            json=envelope(replacement_key, "hello", old.name, hello(replacement_key, tmp_path, old.name)))
        assert response.status_code == 200
        new, new_token = reg.active_device(old.name), response.json()["token"]
        assert new.id != old.id and new.owner == "telegram:bob"
        assert reg.credential_for(token, clock.now, include_revoked=True).revoked_at == event
        for offset in (0, 9, 10):
            clock.now = event + offset
            response = web.post(device_path(kind), headers=headers(token),
                                json=envelope(key, kind, old.id, body_for(kind, key, tmp_path, old.name)))
            if offset < 10:
                explicit(response)
                assert provider.verify_token(token=token) is not None
            else:
                core_generic(response)
                assert provider.verify_token(token=token) is None
            active_poll(web, relay, new, new_token, replacement_key)


@pytest.mark.parametrize("public", [False, True])
def test_same_owner_repair_inside_window_keeps_original_end(tmp_path, monkeypatch, public):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, relay, _, provider), TestClient(app) as web:
        old, token, key = paired(reg, tmp_path, now=clock.now - 1)
        active_poll(web, relay, old, token, key)
        event = clock.now
        reg.revoke(old.name, event)
        clock.advance(3)
        replacement_key = SigningKey.generate()
        code = reg.mint(old.name, clock.now, owner=old.owner)
        response = web.post(device_path("hello"), headers=headers(code),
                            json=envelope(replacement_key, "hello", old.name, hello(replacement_key, tmp_path, old.name)))
        assert response.status_code == 200
        new, new_token = reg.active_device(old.name), response.json()["token"]
        assert new.id == old.id
        for offset in (9, 10, 12, 86400):
            clock.now = event + offset
            response = web.post(device_path("poll"), headers=headers(token), json=envelope(key, "poll", old.id, {}))
            if offset == 9:
                explicit(response)
                assert provider.verify_token(token=token) is not None
            else:
                core_generic(response)
                assert provider.verify_token(token=token) is None
            assert reg.credential_for(token, clock.now, include_revoked=True).revoked_at == event
            active_poll(web, relay, new, new_token, replacement_key)


@pytest.mark.parametrize("public", [False, True])
def test_dispose_enabled_routes_closes_retained_window(tmp_path, monkeypatch, public):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, _, _, provider), TestClient(app) as web:
        device, token, _ = paired(reg, tmp_path, now=clock.now - 1)
        assert provider.routes.enabled
        reg.revoke(device.name, clock.now)
        clock.advance(3)
        assert provider.verify_token(token=token) is not None
        assert web.get(FOREIGN, headers=headers(token)).status_code == 200
        provider.routes.dispose()
        assert not provider.routes.enabled and provider.verify_token(token=token) is None
        assert web.get(FOREIGN, headers=headers(token)).status_code == 401
        assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200


@pytest.mark.parametrize("public", [False, True])
def test_gateway_clock_setback_reopens_only_inside_window(tmp_path, monkeypatch, public):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, _, _, _), TestClient(app) as web:
        device, token, _ = paired(reg, tmp_path, now=clock.now - 1)
        assert web.get(FOREIGN, headers=headers(token)).status_code == 200
        event = clock.now
        reg.revoke(device.name, event)
        for offset, status in ((5, 200), (10, 401), (5, 200), (-1, 401)):
            clock.now = event + offset
            assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200
            assert web.get(FOREIGN, headers=headers(token)).status_code == status


@pytest.mark.parametrize("public", [False, True])
def test_foreign_gate_admits_only_live_unused_pairing_code(tmp_path, monkeypatch, public):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch, public) as (app, reg, relay, _, provider), TestClient(app) as web:
        key = SigningKey.generate()
        code = reg.mint("pairing", clock.now)
        assert web.get(FOREIGN).status_code == 401
        assert provider.verify_token(token=code) is not None
        assert web.get(FOREIGN, headers=headers(code)).status_code == 200
        response = web.post(device_path("hello"), headers=headers(code),
                            json=envelope(key, "hello", "pairing", hello(key, tmp_path, "pairing")))
        assert response.status_code == 200
        assert provider.verify_token(token=code) is None
        assert web.get(FOREIGN, headers=headers(code)).status_code == 401
        active_poll(web, relay, reg.active_device("pairing"), response.json()["token"], key)
        key = SigningKey.generate()
        code = reg.mint("pairing", clock.now)
        assert web.get(FOREIGN, headers=headers(code)).status_code == 200
        response = web.post(device_path("hello"), headers=headers(code),
                            json=envelope(key, "hello", "pairing", hello(key, tmp_path, "pairing")))
        assert response.status_code == 200
        assert provider.verify_token(token=code) is None
        assert web.get(FOREIGN, headers=headers(code)).status_code == 401
        active_poll(web, relay, reg.active_device("pairing"), response.json()["token"], key)
        expires = reg.mint("expiring", clock.now)
        clock.advance(599)
        assert web.get(FOREIGN, headers=headers(expires)).status_code == 200
        clock.advance()
        assert provider.verify_token(token=expires) is None
        assert web.get(FOREIGN, headers=headers(expires)).status_code == 401
        assert web.get(FOREIGN, headers=headers(FOREIGN_TOKEN)).status_code == 200


@pytest.mark.parametrize("kind", ["hello", "poll", "chunk", "result"])
@pytest.mark.parametrize("delay", [10, 301, 86400])
def test_ungated_router_answers_retained_proof_without_other_authority(tmp_path, monkeypatch, kind, delay):
    clock = Clock(monkeypatch)
    with gateway(tmp_path, monkeypatch) as (app, reg, relay, module, _), TestClient(app) as web:
        device, token, key = paired(reg, tmp_path, now=clock.now - 1)
        active_poll(web, relay, device, token, key)
        owner = reg.path.with_name("owner.json")
        assert owner.exists()
        reg.revoke(device.name, clock.now)
        explicit(web.post(device_path(kind), headers=headers(token),
                          json=envelope(key, kind, device.id, body_for(kind, key, tmp_path, device.name))))
        relay.last_seen.clear()
        owner.unlink()
        monkeypatch.setattr(module, "_ORIGIN", None)
        clock.advance(delay)
        body = body_for(kind, key, tmp_path, device.name)
        wire = envelope(key, kind, device.id, body)
        core_generic(web.post(device_path(kind), headers=headers(token), json=wire))
        # Reuse the real mounted routes, deliberately omitting all core middleware.
        with TestClient(FastAPI(routes=app.routes)) as ungated:
            explicit(ungated.post(device_path(kind), headers=headers(token), json=wire))
            response = ungated.post(device_path(kind), headers=headers(token),
                                    json=invalid_wire(kind, key, device.id, body, "wrong-signature"))
            generic(response)
            assert response.json() == {"detail": "unknown device credential"}
        assert not relay.last_seen and not owner.exists()
