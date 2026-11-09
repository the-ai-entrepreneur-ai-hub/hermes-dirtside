"""Sender authority, private discovery and migrations from the shipped registry."""
import importlib.util
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from ruamel.yaml import YAML
from gateway.session_context import clear_session_vars, set_session_vars
from nacl.signing import SigningKey

from dirtside.commands import Commands
from dirtside.model import Outcome, RequestState
from dirtside.protocol import DeviceHello
from dirtside.registry import Registry
from dirtside.relay import Relay


@contextmanager
def sender(user="A", platform="telegram", surface=None, source=""):
    tokens = set_session_vars(session_key="shared-group", session_id="other", platform=platform,
                              user_id=user, source=source)
    try:
        yield context(surface or platform)
    finally:
        clear_session_vars(tokens)


def context(surface="telegram", owners=()):
    return SimpleNamespace(session_surface=lambda: surface, ask_choice=lambda q, choices: "server",
                           get_config=lambda name, default=None: list(owners) if name == "owners" else default)


def pair_for(reg, relay, root, user="A", name="private-laptop"):
    with sender(user) as ctx:
        reply = Commands(ctx, reg, relay)("pair " + name)
    code = re.search(r"--code=(\S+)", reply)[1]
    hello = DeviceHello(bytes(SigningKey.generate().verify_key), name, "private-os", "",
                        str(root), str(root), "0.1.0")
    return reg.complete_pairing(name, hello, int(time.time()), code=code)[0]


def test_owner_commands(tmp_path):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    device = pair_for(reg, relay, tmp_path)
    relay.touch(device.id)
    with sender("B") as ctx:
        cmd = Commands(ctx, reg, relay)
        assert "private-laptop" not in cmd("devices")
        assert "private-laptop" not in cmd("")
        assert "telegram:B" in cmd("")
        assert cmd("use private-laptop") == cmd("use missing").replace("missing", "private-laptop")
        assert reg.target("shared-group") is None
        choices = []
        ctx.ask_choice = lambda q, offered: choices.extend(offered) or "server"
        cmd("use")
        assert choices == ["server"]
        assert cmd("revoke private-laptop") == cmd("revoke missing").replace("missing", "private-laptop")
        assert reg.active_device(device.name) is not None
    with sender("A") as ctx:
        cmd = Commands(ctx, reg, relay)
        assert "private-laptop" in cmd("devices")
        cmd("use private-laptop")
        assert reg.target("shared-group") == device.id
        assert "Revoked" in cmd("revoke private-laptop")


@pytest.mark.parametrize("user,owners,allowed", [
    ("A", [], True), ("B", ["telegram:A"], False), ("A", ["telegram:A"], True),
])
def test_pairing_authority(tmp_path, user, owners, allowed):
    reg = Registry(tmp_path / "data.db")
    with sender(user):
        reply = Commands(context(owners=owners), reg, Relay(reg))("pair fresh")
    assert ("--code=" in reply) is allowed
    assert len(reg._connection().execute("SELECT * FROM devices").fetchall()) == int(allowed)


def test_global_and_local_owners(tmp_path):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    device = pair_for(reg, relay, tmp_path)
    for ctx, user, platform, source in [
        (context(owners=["telegram:B"]), "B", "telegram", ""),
        (context("cli"), "", "", "cli"),
    ]:
        with sender(user, platform, source=source):
            cmd = Commands(ctx, reg, relay)
            assert device.name in cmd("devices")
            cmd("use " + device.name)
            assert reg.target("shared-group") == device.id


@pytest.mark.parametrize("surface,platform,user,source,expected", [
    ("cli", "", "", "", "local"), ("tui", "", "", "tui", "local"),
    ("desktop", "local", "", "desktop", "local"), ("acp", "", "", "", "local"),
    ("", "", "", "cli", "local"), ("", "", "", "acp", "local"),
    ("", "", "", "gui", "local"),
    ("cli", "cli", "local", "", "cli:local"),
    ("telegram", "telegram", "local", "", "telegram:local"),
    ("cli", "telegram", "A", "cli", "telegram:A"),
    ("telegram", "telegram", "", "", ""), ("", "", "", "", ""),
])
def test_sender_provenance(surface, platform, user, source, expected):
    from dirtside.access import Access
    with sender(user, platform, surface=surface, source=source):
        assert Access(context(surface)).identity() == expected


@pytest.mark.parametrize("owners", [None, "telegram:A", ["A"], [1], ["local", "local"],
                                    ["telegram:"], ["telegram:A\n"], [""], ["email:bad\rvalue"],
                                    ["irc:bad\tuser"], ["irc:\0"], ["irc:\u202e"]])
def test_bad_owners_refused(owners):
    from dirtside.access import Access
    with pytest.raises(ValueError, match="owners"):
        Access(context(owners=()), owners=owners)


@pytest.mark.parametrize("platform,user", [
    ("email", "build+release@example.test"), ("email", '"build releases"@example.test'),
    ("signal", "+15550102000"), ("irc", "[native-nick]"),
])
def test_native_sender_spelling_can_own_device(tmp_path, platform, user):
    if platform == "email":
        from plugins.platforms.email.adapter import _extract_email_address
        assert _extract_email_address(user) == user
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    with sender(user, platform) as ctx:
        reply = Commands(ctx, reg, relay)("pair native")
        assert "--code=" in reply
    code = re.search(r"--code=(\S+)", reply)[1]
    hello = DeviceHello(bytes(SigningKey.generate().verify_key), "native", "test-os", "",
                        str(tmp_path), str(tmp_path), "0.1.0")
    device = reg.complete_pairing("native", hello, int(time.time()), code=code)[0]
    with sender("other", platform) as ctx:
        assert "native" not in Commands(ctx, reg, relay)("devices")
    with sender(user, platform) as ctx:
        cmd = Commands(ctx, reg, relay)
        assert device.owner == f"{platform}:{user}"
        assert "native" in cmd("devices")
        cmd("use native")
        assert reg.target("shared-group") == device.id


def test_owner_config_schema():
    manifest = YAML(typ="safe").load((Path(__file__).resolve().parents[1] / "plugin.yaml").read_text())
    assert manifest["config_schema"]["owners"]["type"] == "list"
    assert manifest["config_schema"]["owners"]["default"] == []


def test_repair_transfers_pending_owner(tmp_path):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    first = pair_for(reg, relay, tmp_path)
    reg.revoke(first.name, int(time.time()))
    second = pair_for(reg, relay, tmp_path, user="B")
    assert second.id != first.id and second.owner == "telegram:B"
    assert reg.device_by_id(first.id) is None
    with sender("A") as ctx:
        assert first.name not in Commands(ctx, reg, relay)("devices")
    with sender("B") as ctx:
        assert first.name in Commands(ctx, reg, relay)("devices")


def test_pending_names_cannot_be_stolen(tmp_path):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    with sender("A") as ctx:
        code = re.search(r"--code=(\S+)", Commands(ctx, reg, relay)("pair pending"))[1]
    with sender("B") as ctx:
        cmd = Commands(ctx, reg, relay)
        assert "--code=" not in cmd("pair pending")
        cmd("revoke pending")
    assert reg.credential_for(code, int(time.time())) is not None


def test_old_registry_migration(tmp_path):
    from test_registry import request
    source = Path(__file__).with_name("fixtures") / "registry_0ae9359.txt"
    spec = importlib.util.spec_from_loader("dirtside._baseline_registry", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source.read_text(), str(source), "exec"), module.__dict__)
    old = module.Registry(tmp_path / "data.db")
    old.mint("old-device", 100)
    hello = DeviceHello(bytes(SigningKey.generate().verify_key), "old-device", "old-os", "",
                        str(tmp_path), str(tmp_path), "0.1.0")
    device, token = old.complete_pairing("old-device", hello, 101)
    pending = old.mint("pending", int(time.time()))
    old.set_target("old-chat", device.id)
    old.log(request(device, n=1))
    finished = request(device, n=2)
    old.log(finished)
    old.running(finished.id)
    old.close(finished.id, Outcome(RequestState.FINISHED, 0, 12, False, "complete"), int(time.time()))
    before_requests = sqlite3.connect(old.path).execute("SELECT * FROM requests ORDER BY id").fetchall()
    before = sqlite3.connect(old.path).execute("SELECT * FROM devices ORDER BY name").fetchall()
    for _ in range(3):
        upgraded = Registry(old.path)
        assert upgraded.device_by_id(device.id).owner == "local"
        assert upgraded.credential_for(token, 102).id == device.id
        assert upgraded.target("old-chat") == device.id
        assert upgraded.credential_for(pending, int(time.time())).name == "pending"
        assert upgraded.relay_seed == old.relay_seed and upgraded.local_secret == old.local_secret
        with sqlite3.connect(old.path) as conn:
            after = conn.execute("SELECT * FROM devices ORDER BY name").fetchall()
            assert [row[:-1] for row in after] == before
            assert all(row[-1] == "local" for row in after)
            assert conn.execute("SELECT * FROM requests ORDER BY id").fetchall() == before_requests

def test_owner_list_bounds():
    from dirtside.access import Access
    owners = ["telegram:" + str(n) for n in range(64)]
    assert len(Access(context(), owners=owners).owners) == 64
    assert Access(context(), owners=["telegram:" + "a" * 256]).owners
    for invalid in [owners + ["telegram:64"], ["telegram:" + "a" * 257]]:
        with pytest.raises(ValueError, match="owners"):
            Access(context(), owners=invalid)


def test_cron_keeps_host_authority_without_a_messaging_sender():
    from dirtside.access import Access
    tokens = set_session_vars(platform="", user_id="", source="", cron_session="1")
    try:
        assert Access(context("")).identity() == "local"
    finally:
        clear_session_vars(tokens)


def test_concurrent_pairing_cannot_replace_another_sender(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    barrier = threading.Barrier(2)

    def mint(user):
        with sender(user) as ctx:
            barrier.wait()
            return Commands(ctx, reg, relay)("pair shared-name")

    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(mint, ["A", "B"]))
    assert sum("--code=" in reply for reply in replies) == 1
    rows = reg._connection().execute("SELECT owner FROM devices WHERE revoked_at IS NULL").fetchall()
    assert len(rows) == 1 and rows[0]["owner"] in {"telegram:A", "telegram:B"}


@pytest.mark.parametrize("identity", ["", "cli", "local\n", "telegram:", "telegram:" + "a" * 257])
def test_local_sender_is_bounded_and_rechecked(tmp_path, identity):
    from dataclasses import asdict, replace
    from fastapi.testclient import TestClient
    from network_support import mounted
    from dirtside.local import PREFIX
    from test_registry import request
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    device = pair_for(reg, relay, tmp_path)
    relay.touch(device.id)
    with mounted(tmp_path, relay=relay) as (app, *_), TestClient(app, client=("127.0.0.1", 10)) as web:
        response = web.post(PREFIX + "/exec", headers={"Authorization": "Bearer " + reg.local_secret},
                            json=asdict(replace(request(device), sender=identity)))
        assert response.status_code == 403
        assert not relay.handles and reg.recent(10) == []

@pytest.mark.parametrize("source,surface", [("cli", "cli"), ("tui", "tui"), ("gui", "desktop"), ("acp", "acp")])
@pytest.mark.parametrize("user", ["", f"uid:{os.getuid()}", f"uid:{os.getuid() + 1}", "host-label"])
def test_canonical_local_actor_uses_real_core_policy(tmp_path, source, surface, user):
    from dirtside.access import Access
    from gateway.session_policy import LocalSessionPolicy, policy_scope
    from hermes_cli.plugin_session import session_surface
    policy = LocalSessionPolicy(source, surface, str(tmp_path), None, (), "{}", "{}", "{}",
                                ignore_user_config=True)
    ctx = context()
    ctx.session_surface = session_surface
    with sender(user, "local"), policy_scope(policy):
        expected = "local" if user in ("", f"uid:{os.getuid()}") else "local:" + user
        assert Access(ctx).identity() == expected


@pytest.mark.parametrize("surface", ["local", "cli", "tui", "desktop", "acp"])
@pytest.mark.parametrize("user", ["", f"uid:{os.getuid()}", f"uid:{os.getuid() + 1}", "local"])
def test_local_platform_requires_same_uid(surface, user):
    from dirtside.access import Access
    with sender(user, "local", surface=surface):
        expected = "local" if surface != "local" and user in ("", f"uid:{os.getuid()}") else (
            "local:" + user if user else "")
        assert Access(context(surface)).identity() == expected


@pytest.mark.parametrize("platform", ["telegram", "discord", "cli", "tui"])
@pytest.mark.parametrize("user", ["local", f"uid:{os.getuid()}"])
def test_messaging_uid_cannot_become_local(platform, user):
    from dirtside.access import Access
    with sender(user, platform, surface="local", source="cli"):
        assert Access(context("local")).identity() == f"{platform}:{user}"