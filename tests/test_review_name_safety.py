"""Implicit names never redirect privileged work to an untrusted device."""
import inspect
import re
import time
from contextlib import contextmanager

import pytest
from nacl.signing import SigningKey

from dirtside.commands import Commands
from dirtside.environment import EnvironmentConnectionError
from dirtside.model import OnDevice, Server
from dirtside.protocol import DeviceHello
from dirtside.provider import DirtsideProvider, resolve_target
from dirtside.registry import Registry
from dirtside.relay import Relay
from fake_device import FakeDevice
from test_review_device_owners import context, sender


@contextmanager
def actor(identity, owners=()):
    platform, _, user = identity.partition(":")
    with sender(user if identity != "local" else "", platform if identity != "local" else "",
                surface=platform if identity != "local" else "tui",
                source="" if identity != "local" else "tui"):
        yield context("tui" if identity == "local" else platform, owners)


def pair_as(reg, relay, root, identity, name="mac", owners=()):
    with actor(identity, owners) as ctx:
        reply = Commands(ctx, reg, relay, default_target=name)("pair " + name)
    code = re.search(r"--code=(\S+)", reply)[1]
    key = SigningKey.generate()
    hello = DeviceHello(bytes(key.verify_key), name, "private-os", "", str(root), str(root), "0.1.0")
    device, token = reg.complete_pairing(name, hello, int(time.time()), code=code)
    return device, token, key


def target(cmd, key="shared-group"):
    kwargs = {"require_contact": False}
    if hasattr(cmd, "access"):
        kwargs["access"] = cmd.access
    return resolve_target(key, False, cmd.default_target, cmd.registry, cmd.relay, **kwargs)


@pytest.mark.parametrize("identity,owners", [("local", []), ("telegram:ops", ["telegram:ops"])])
def test_untrusted_implicit_default_uses_server(tmp_path, identity, owners):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    device, _, _ = pair_as(reg, relay, tmp_path, "telegram:bob")
    relay.touch(device.id)
    with actor(identity, owners) as ctx:
        cmd = Commands(ctx, reg, relay, default_target="mac")
        assert isinstance(target(cmd), Server)
        assert "targets server" in cmd("")
        cmd("use mac")
        assert isinstance(target(cmd), OnDevice)
        cmd("use server")
        assert isinstance(target(cmd), Server)
    reg.set_target("shared-group", None)
    for owner in ("local", "telegram:ops", identity):
        name = "trusted-" + str(len(reg.devices()))
        trusted, _, _ = pair_as(reg, relay, tmp_path, owner, name)
        with actor(identity, ["telegram:ops"]) as ctx:
            cmd = Commands(ctx, reg, relay, default_target=name)
            assert target(cmd, "new-conversation-" + name).device.id == trusted.id


@pytest.mark.parametrize("previous_owner", ["local", "telegram:alice"])
def test_cross_owner_repair_keeps_stale_target_closed(tmp_path, previous_owner):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    first, old_token, _ = pair_as(reg, relay, tmp_path, previous_owner)
    reg.set_target("shared-group", first.id)
    reg.revoke("mac", int(time.time()))
    second, _, _ = pair_as(reg, relay, tmp_path, "telegram:bob")
    assert second.id != first.id
    assert reg.target("shared-group") == first.id and reg.device_by_id(first.id) is None
    assert reg.credential_for(old_token, int(time.time())) is None
    with actor("local") as ctx:
        with pytest.raises(EnvironmentConnectionError, match="no longer paired"):
            target(Commands(ctx, reg, relay))
    reg.revoke("mac", int(time.time()))
    third, _, _ = pair_as(reg, relay, tmp_path, previous_owner)
    assert third.id not in {first.id, second.id}
    reg.revoke("mac", int(time.time()))
    same_owner, _, _ = pair_as(reg, relay, tmp_path, previous_owner)
    assert same_owner.id == third.id


@pytest.mark.parametrize("identity,owners", [("local", []), ("telegram:ops", ["telegram:ops"])])
def test_privileged_use_names_unprivileged_owner(tmp_path, identity, owners):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    device, _, _ = pair_as(reg, relay, tmp_path, "telegram:bob")
    with actor(identity, owners) as ctx:
        cmd = Commands(ctx, reg, relay)
        assert "owned by telegram:bob" in cmd("use mac")
        assert reg.target("shared-group") == device.id
    with actor("telegram:bob") as ctx:
        assert "owned by" not in Commands(ctx, reg, relay)("use mac")
    trusted, _, _ = pair_as(reg, relay, tmp_path, "local", "trusted")
    with actor(identity, owners) as ctx:
        assert "owned by" not in Commands(ctx, reg, relay)("use trusted")
        assert reg.target("shared-group") == trusted.id


def test_implicit_default_never_sends_operator_work_to_squatter(tmp_path):
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    server, device_root = tmp_path / "server", tmp_path / "device"
    server.mkdir()
    device_root.mkdir()
    device, token, key = pair_as(reg, relay, device_root, "telegram:bob")
    with FakeDevice(relay, device, token, key) as fake, actor("local") as ctx:
        ctx.session_cwd = lambda: str(server)
        cmd = Commands(ctx, reg, relay)
        kwargs = {"access": cmd.access} if "access" in inspect.signature(DirtsideProvider).parameters else {}
        env = DirtsideProvider(reg, relay, "mac", **kwargs).create_environment(cwd=str(server), timeout=120)
        try:
            result = env.execute("pwd")
            assert result["returncode"] == 0 and result["output"].strip() == str(server)
            assert fake.posts == [] and reg.recent(50) == []
        finally:
            env.cleanup()


def test_pairing_name_availability_disclosure(tmp_path):
    from pathlib import Path
    reg = Registry(tmp_path / "data.db")
    relay = Relay(reg)
    pair_as(reg, relay, tmp_path, "telegram:alice")
    with actor("telegram:bob") as ctx:
        cmd = Commands(ctx, reg, relay)
        assert cmd("pair mac") == "Pairing is unavailable for this sender."
        assert "--code=" in cmd("pair free")
        assert cmd("use mac") == cmd("use missing").replace("missing", "mac")
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "Pairing reveals whether a name is available" in readme
