"""Explicit re-pairing also restores a previously revoked named identity."""
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from fake_device import FakeDevice
from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from network_support import mounted, until

from dirtside.provider import ConversationEnvironment, DirtsideProvider
from dirtside.protocol import sign
from test_registry import paired, request
from test_routes import API, headers, hello


def test_repair_after_revoke_restores_the_existing_conversation_choice(tmp_path):
    with mounted(tmp_path) as (app, reg, relay, _), TestClient(app) as client:
        device, old_token, old_key = paired(reg, tmp_path, now=int(time.time()))
        reg.set_target("chosen-chat", device.id)
        with FakeDevice(relay, device, old_token, old_key):
            env = ConversationEnvironment(DirtsideProvider(reg, relay), "chosen-chat", False,
                                          "~", 120, "default")
            assert env.execute("printf before")["output"] == "before"
        reg.revoke(device.name, int(time.time()))
        relay.revoke(device.id)
        key, now = SigningKey.generate(), int(time.time())
        code = reg.mint(device.name, now)
        response = client.post(API + "/device/pair", headers=headers(code),
                               json=sign(key, "hello", device.name, hello(key, tmp_path, device.name)))
        assert response.status_code == 200
        assert response.json()["device_id"] == device.id
        replacement = reg.active_device(device.name)
        assert replacement.pubkey == bytes(key.verify_key)
        assert reg.credential_for(old_token, now) is reg.credential_for(code, now) is None
        assert reg.target("chosen-chat") == device.id
        with FakeDevice(relay, replacement, response.json()["token"], key):
            assert env.execute("printf restored")["output"] == "restored"
            env.cleanup()


def test_repair_invalidates_an_old_authenticated_poll_before_new_work(tmp_path):
    with mounted(tmp_path) as (app, reg, relay, _), TestClient(app) as client:
        device, token, key = paired(reg, tmp_path, now=int(time.time()))
        with ThreadPoolExecutor(1) as callers:
            old_poll = callers.submit(client.post, API + "/device/poll", headers=headers(token),
                                       json=sign(key, "poll", device.id, {}))
            until(lambda: relay.is_online(device.id))
            new_key = SigningKey.generate()
            code = reg.mint(device.name, int(time.time()))
            response = client.post(API + "/device/pair", headers=headers(code),
                                   json=sign(new_key, "hello", device.name, hello(new_key, tmp_path, device.name)))
            assert response.status_code == 200
            handle = relay.submit(request(device))
            try:
                assert old_poll.result(timeout=2).status_code == 401
                assert not relay.is_online(device.id)
                new_poll = client.post(API + "/device/poll", headers=headers(response.json()["token"]),
                                       json=sign(new_key, "poll", device.id, {"running": []}))
                assert new_poll.status_code == 200 and new_poll.json()["body"]["exec"]["id"] == handle.req.id
            finally:
                handle.kill()
                relay.revoke(device.id)
                handle.stdout.close()


def test_overlapping_pairings_publish_the_current_key_in_commit_order(tmp_path, monkeypatch):
    with mounted(tmp_path) as (app, reg, relay, module), TestClient(app) as client:
        device, _, _ = paired(reg, tmp_path, now=int(time.time()))
        keys = [SigningKey.generate(), SigningKey.generate()]
        first_committed, release_first, second_parsed, second_committed = [threading.Event() for _ in range(4)]
        complete, parse = reg.complete_pairing, module.wire.parse_hello
        def delayed(*args, **kwargs):
            result = complete(*args, **kwargs)
            if result[0].pubkey == bytes(keys[0].verify_key):
                first_committed.set()
                assert release_first.wait(5)
            else:
                second_committed.set()
            return result
        def observed(body):
            parsed = parse(body)
            if parsed.pubkey == bytes(keys[1].verify_key):
                second_parsed.set()
            return parsed
        monkeypatch.setattr(reg, "complete_pairing", delayed)
        monkeypatch.setattr(module.wire, "parse_hello", observed)
        def pair(key, code):
            return client.post(API + "/device/pair", headers=headers(code),
                               json=sign(key, "hello", device.name, hello(key, tmp_path, device.name)))
        with ThreadPoolExecutor(2) as callers:
            first = callers.submit(pair, keys[0], reg.mint(device.name, int(time.time())))
            try:
                assert first_committed.wait(2)
                second = callers.submit(pair, keys[1], reg.mint(device.name, int(time.time())))
                assert second_parsed.wait(2)
                second_committed.wait(0.5)
            finally:
                release_first.set()
            assert first.result(timeout=2).status_code == 200
            response = second.result(timeout=2)
            assert response.status_code == 200
        current = reg.active_device(device.name)
        handle = relay.submit(request(current))
        try:
            response = client.post(API + "/device/poll", headers=headers(response.json()["token"]),
                                   json=sign(keys[1], "poll", current.id, {"running": []}))
            assert response.status_code == 200
            assert response.json()["body"]["exec"]["id"] == handle.req.id
        finally:
            handle.kill()
            handle.stdout.close()
