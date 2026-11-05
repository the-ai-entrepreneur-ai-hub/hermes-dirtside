"""Registry lifecycle and concurrent SQLite contracts."""
import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from nacl.signing import SigningKey

from dirtside.model import ExecRequest, Outcome, PAIR_TTL_S, Pending, RequestState
from dirtside.protocol import DeviceHello
from dirtside.registry import Registry


def paired(registry, root, name="macbook", now=100):
    key = SigningKey.generate()
    hello = DeviceHello(bytes(key.verify_key), name, "macOS", "arm64", str(root), str(root), "0.1.0")
    registry.mint(name, now)
    device, token = registry.complete_pairing(name, hello, now + 1)
    return device, token, key


def request(device, n=1, session="chat", command="pwd"):
    return ExecRequest(f"r_{n:024x}", device.id, session, "default", command, command, False, 120, None, device.home)


def test_pairing_code_lifecycle(tmp_path):
    reg = Registry(tmp_path / "data.db")
    code = reg.mint("macbook", 100)
    assert reg.credential_for(code, 100) == Pending("macbook", 100 + PAIR_TTL_S)
    assert reg.credential_for(code, 100 + PAIR_TTL_S) is None
    assert reg.credential_for("wrong", 100) is None
    key = SigningKey.generate()
    hello = DeviceHello(bytes(key.verify_key), "macbook", "macOS", "arm64", str(tmp_path), str(tmp_path), "0.1.0")
    device, token = reg.complete_pairing("macbook", hello, 101)
    assert device == reg.credential_for(token, 10000) == reg.active_device("macbook") == reg.device_by_id(device.id)
    assert reg.credential_for(code, 101) is None
    with pytest.raises(ValueError):
        reg.complete_pairing("macbook", hello, 102)
    with sqlite3.connect(reg.path) as conn:
        stored = conn.execute("SELECT token_hash FROM devices WHERE id=?", (device.id,)).fetchone()[0]
    assert stored == hashlib.sha256(token.encode()).digest()
    assert stored not in (code.encode(), token.encode())
    assert code != token and len(device.id) == 32


def test_pairing_expired_and_reminted(tmp_path):
    reg = Registry(tmp_path / "data.db")
    device, old, key = paired(reg, tmp_path)
    code = reg.mint("macbook", 200)
    newer = reg.mint("macbook", 201)
    assert reg.credential_for(code, 202) is None
    assert isinstance(reg.credential_for(newer, 202), Pending)
    hello = DeviceHello(bytes(key.verify_key), "macbook", "macOS", "arm64", str(tmp_path), str(tmp_path), "0.1.0")
    with pytest.raises(ValueError):
        reg.complete_pairing("macbook", hello, 201 + PAIR_TTL_S)
    second, token, _ = paired(reg, tmp_path, now=1000)
    assert second.id == device.id and second.pubkey != device.pubkey
    assert reg.credential_for(old, 1002) is None
    assert reg.device_by_id(device.id) == second
    assert reg.credential_for(token, 1002) == second


def test_pairing_concurrent_completion(tmp_path):
    reg = Registry(tmp_path / "data.db")
    reg.mint("macbook", 100)
    hello = DeviceHello(bytes(SigningKey.generate().verify_key), "macbook", "macOS", "arm64",
                        str(tmp_path), str(tmp_path), "0.1.0")
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait()
        try:
            return reg.complete_pairing("macbook", hello, 101)
        except ValueError:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: complete(), range(2)))
    assert sum(r is not None for r in results) == 1


def test_revoke(tmp_path):
    reg = Registry(tmp_path / "data.db")
    device, token, _ = paired(reg, tmp_path)
    assert reg.revoke(device.name, 102) == device
    assert reg.revoke(device.name, 103) is None
    assert reg.active_device(device.name) is None
    assert reg.device_by_id(device.id) is None
    assert reg.credential_for(token, 104) is None
    code = reg.mint("pending", 104)
    assert reg.revoke("pending", 105) is None
    assert reg.credential_for(code, 105) is None


def test_targets(tmp_path):
    reg = Registry(tmp_path / "data.db")
    device, _, _ = paired(reg, tmp_path)
    assert reg.target("chat") is None
    reg.set_target("chat", device.id)
    assert Registry(reg.path).target("chat") == device.id
    reg.revoke(device.name, 102)
    assert reg.target("chat") == device.id
    reg.set_target("chat", "server")
    assert Registry(reg.path).target("chat") == "server"
    reg.set_target("chat", None)
    assert reg.target("chat") is None
    with pytest.raises(ValueError, match="not paired"):
        reg.set_target("chat", "missing")
    with pytest.raises(ValueError):
        reg.set_target("", device.id)

def test_legacy_targets_migrate_without_losing_revoked_selections(tmp_path):
    reg = Registry(tmp_path / "data.db")
    device, _, _ = paired(reg, tmp_path)
    with sqlite3.connect(reg.path) as conn:
        conn.execute("DROP TABLE targets")
        conn.execute("CREATE TABLE targets (session_key TEXT PRIMARY KEY, "
                     "device_id TEXT NOT NULL REFERENCES devices(id), set_at INTEGER NOT NULL)")
        conn.execute("INSERT INTO targets VALUES(?,?,?)", ("chat", device.id, 123))
    reg.revoke(device.name, 124)
    migrated = Registry(reg.path)
    assert migrated.target("chat") == device.id
    with sqlite3.connect(reg.path) as conn:
        assert conn.execute("SELECT * FROM targets").fetchall() == [("chat", device.id, 123)]
        assert conn.execute("PRAGMA foreign_key_list(targets)").fetchall() == []
    migrated.set_target("other", "server")
    assert Registry(reg.path).target("other") == "server"


def test_request_log(tmp_path):
    reg = Registry(tmp_path / "data.db")
    device, _, _ = paired(reg, tmp_path)
    first = request(device, command="x" * 200)
    reg.log(first)
    reg.log(request(device, 2, "other"))
    row = reg.recent(1, "chat")[0]
    assert row.id == first.id and row.preview == "x" * 120 and row.state is RequestState.QUEUED
    out = Outcome(RequestState.FINISHED, 3, 40, False, "")
    reg.close(first.id, out, 200)
    row = reg.recent(1, "chat")[0]
    assert row.exit_code == 3 and row.finished_at == 200 and row.state is RequestState.FINISHED
    assert len(reg.recent(10)) == 2 and reg.recent(0) == []
    assert "script" not in row.__dataclass_fields__


def test_mark_stale_lost(tmp_path):
    reg = Registry(tmp_path / "data.db")
    device, _, _ = paired(reg, tmp_path)
    for n in range(3):
        reg.log(request(device, n))
    reg.close(request(device, 2).id, Outcome(RequestState.FINISHED, 0, 2, False, ""), 105)
    with sqlite3.connect(reg.path) as conn:
        conn.execute("UPDATE requests SET state='running' WHERE id=?", (request(device, 1).id,))
    reg.mark_stale_lost(110)
    rows = {r.id: r for r in reg.recent(10)}
    for n in (0, 1):
        row = rows[request(device, n).id]
        assert (row.state, row.exit_code, row.finished_at) == (RequestState.LOST, 124, 110)
    assert rows[request(device, 2).id].state is RequestState.FINISHED


def test_relay_key_private(tmp_path):
    path = tmp_path / "data.db"
    reg = Registry(path)
    key = tmp_path / "relay.key"
    assert key.stat().st_mode & 0o777 == 0o600
    assert len(reg.relay_seed) == 32
    assert Registry(path).relay_seed == reg.relay_seed
    key.chmod(0o644)
    assert Registry(path).relay_seed == reg.relay_seed
    assert key.stat().st_mode & 0o777 == 0o600


def test_relay_key_refuses_links_and_damage(tmp_path):
    key, target = tmp_path / "relay.key", tmp_path / "other"
    target.write_bytes(b"x" * 32)
    key.symlink_to(target)
    with pytest.raises(OSError):
        Registry(tmp_path / "data.db")
    assert target.read_bytes() == b"x" * 32
    key.unlink()
    key.write_bytes(b"broken")
    with pytest.raises(ValueError):
        Registry(tmp_path / "data.db")


def test_thread_local_wal(tmp_path):
    reg = Registry(tmp_path / "data.db")
    main = reg._connection()
    barrier = threading.Barrier(4)
    connections = []

    def worker(n):
        conn = reg._connection()
        connections.append(conn)
        barrier.wait()
        reg.mint(f"device-{n}", 100)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        return conn is reg._connection()

    with ThreadPoolExecutor(4) as pool:
        assert all(pool.map(worker, range(4)))
    assert len({id(c) for c in [main, *connections]}) == 5
    assert main.execute("SELECT count(*) FROM devices").fetchone()[0] == 4
