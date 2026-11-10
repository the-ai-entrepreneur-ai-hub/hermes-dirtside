"""Thread-local SQLite storage for credentials, targets and request history."""
import fcntl
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from itertools import chain
from pathlib import Path

from .model import PAIR_TTL_S, Device, Pending, RequestRow, RequestState, Revoked
_COLUMNS = "id,name,pubkey,os,arch,home,temp_dir,agent_version,owner"
_ACTIVE = "revoked_at IS NULL AND pubkey IS NOT NULL AND expires_at IS NULL"
_TARGETS = "CREATE TABLE IF NOT EXISTS targets (session_key TEXT PRIMARY KEY, target TEXT NOT NULL, set_at INTEGER NOT NULL)"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS devices (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash BLOB NOT NULL,
 pubkey BLOB, os TEXT, arch TEXT, home TEXT, temp_dir TEXT, agent_version TEXT,
 created_at INTEGER NOT NULL, expires_at INTEGER, revoked_at INTEGER,
 owner TEXT NOT NULL DEFAULT 'local');
CREATE UNIQUE INDEX IF NOT EXISTS devices_active_name ON devices(name)
 WHERE revoked_at IS NULL AND pubkey IS NOT NULL;
CREATE TABLE IF NOT EXISTS retired_credentials (
 token_hash BLOB PRIMARY KEY, id TEXT NOT NULL, name TEXT NOT NULL,
 pubkey BLOB NOT NULL, revoked_at INTEGER NOT NULL);
{_TARGETS};
CREATE TABLE IF NOT EXISTS session_defaults (session_key TEXT PRIMARY KEY, target TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL, session_key TEXT NOT NULL, task_id TEXT NOT NULL,
 state TEXT NOT NULL, preview TEXT NOT NULL, created_at INTEGER NOT NULL,
 finished_at INTEGER, exit_code INTEGER, reason TEXT);
"""

def _device(row):
    return Device(*(row[k] for k in _COLUMNS.split(","))) if row else None
def _hash(token):
    return hashlib.sha256(token.encode()).digest()
class Registry:
    def __init__(self, path):
        self.path, self._local = Path(path), threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._seed() as self.relay_seed:
            self._connection().executescript(_SCHEMA)
            with self._tx() as conn:
                if not any(row["name"] == "owner" for row in conn.execute("PRAGMA table_info(devices)")):
                    conn.execute("ALTER TABLE devices ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'")
                if any(row["name"] == "device_id" for row in conn.execute("PRAGMA table_info(targets)")):
                    conn.execute("ALTER TABLE targets RENAME TO old_targets")
                    conn.execute(_TARGETS)
                    conn.execute("INSERT INTO targets SELECT session_key,device_id,set_at FROM old_targets")
                    conn.execute("DROP TABLE old_targets")
        with self._seed("local.secret", 64) as secret:
            self.local_secret = secret.decode("ascii")

    def _connection(self):
        if not hasattr(self._local, "connection"):
            conn = sqlite3.connect(self.path, timeout=5)
            conn.row_factory = sqlite3.Row
            for pragma in ("busy_timeout=5000", "journal_mode=WAL", "synchronous=NORMAL", "foreign_keys=ON"):
                conn.execute(f"PRAGMA {pragma}")
            self._local.connection = conn
        return self._local.connection

    @contextmanager
    def _tx(self):
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    @contextmanager
    def _seed(self, name="relay.key", size=32):
        fd = os.open(self.path.with_name(name), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b", buffering=0) as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("relay key must be a private regular file")
            os.fchmod(stream.fileno(), 0o600)
            seed = stream.read()
            if not seed:
                seed = secrets.token_bytes(32) if size == 32 else secrets.token_hex(32).encode("ascii")
                stream.write(seed)
                os.fsync(stream.fileno())
            if len(seed) != size or (size == 64 and not re.fullmatch(b"[0-9a-f]{64}", seed)):
                raise ValueError(f"{name} must contain a {size} byte seed")
            yield seed

    def mint(self, name, now, *, owner="local", privileged=False):
        if name == "server" or not re.fullmatch(r"[a-z0-9-]{1,32}", name):
            raise ValueError("device name must contain 1 to 32 lowercase letters, digits or hyphens; 'server' is reserved")
        code = secrets.token_urlsafe(32)
        with self._tx() as conn:
            if not self._name_allowed(conn, name, now, owner, privileged):
                raise ValueError("Pairing is unavailable for this sender")
            conn.execute("UPDATE devices SET revoked_at=? WHERE name=? AND pubkey IS NULL", (now, name))
            conn.execute("INSERT INTO devices(id,name,token_hash,created_at,expires_at,owner) VALUES(?,?,?,?,?,?)",
                         (secrets.token_hex(16), name, _hash(code), now, now + PAIR_TTL_S, owner))
        return code

    def credential_for(self, bearer, now, *, include_revoked=False):
        if type(bearer) is not str:
            return None
        digest = _hash(bearer)
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM devices WHERE (revoked_at IS NULL OR (? AND pubkey IS NOT NULL)) "
                                "AND (expires_at IS NULL OR expires_at>?)", (include_revoked, now))
            retired = conn.execute("SELECT * FROM retired_credentials WHERE ?", (include_revoked,))
            for row in chain(rows, retired):
                if hmac.compare_digest(digest, row["token_hash"]):
                    if row["revoked_at"] is not None:
                        return Revoked(row["id"], row["name"], row["pubkey"], row["revoked_at"])
                    return _device(row) if row["pubkey"] is not None else Pending(row["name"], row["expires_at"])
        return None

    def complete_pairing(self, name, hello, now, *, code=None):
        if hello.name != name:
            raise ValueError("pairing name does not match hello")
        bearer = secrets.token_urlsafe(32)
        with self._tx() as conn:
            row = conn.execute("SELECT id,owner FROM devices WHERE name=? AND pubkey IS NULL "
                               "AND revoked_at IS NULL AND expires_at>? AND (? IS NULL OR token_hash=?)",
                               (name, now, code, _hash(code) if code is not None else None)).fetchone()
            if row is None:
                raise ValueError("pairing code is expired or already used")
            previous = conn.execute("SELECT id,owner FROM devices WHERE name=? AND pubkey IS NOT NULL "
                                    "ORDER BY revoked_at IS NULL DESC,created_at DESC,rowid DESC LIMIT 1", (name,)).fetchone()
            reuse = previous is not None and previous["owner"] == row["owner"]
            identity = previous["id"] if reuse else row["id"]
            if previous and not reuse:
                conn.execute("UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (now, previous["id"]))
            if reuse:
                conn.execute("INSERT OR IGNORE INTO retired_credentials "
                             "SELECT token_hash,id,name,pubkey,COALESCE(revoked_at, ?) FROM devices WHERE id=?", (now, identity))
                conn.execute("DELETE FROM devices WHERE id=?", (row["id"],))
            facts = (hello.pubkey, hello.os, hello.arch, hello.home, hello.temp_dir, hello.agent_version)
            conn.execute("UPDATE devices SET pubkey=?,os=?,arch=?,home=?,temp_dir=?,agent_version=?,"
                         "token_hash=?,expires_at=NULL,revoked_at=NULL,owner=? WHERE id=?",
                         (*facts, _hash(bearer), row["owner"], identity))
            return _device(conn.execute("SELECT * FROM devices WHERE id=?", (identity,)).fetchone()), bearer

    def _find(self, column, value):
        with self._tx() as conn:
            return _device(conn.execute(f"SELECT * FROM devices WHERE {column}=? AND {_ACTIVE}", (value,)).fetchone())

    def active_device(self, name):
        return self._find("name", name)

    def device_by_id(self, device_id):
        return self._find("id", device_id)

    def devices(self):
        with self._tx() as conn:
            return [_device(row) for row in conn.execute(f"SELECT * FROM devices WHERE {_ACTIVE} ORDER BY name")]

    def owners_for_name(self, name):
        with self._tx() as conn:
            return [row["owner"] for row in conn.execute(
                "SELECT owner FROM devices WHERE name=? AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at>?)", (name, int(time.time())))]

    def _name_allowed(self, conn, name, now, owner, privileged):
        rows = conn.execute("SELECT owner FROM devices WHERE name=? AND revoked_at IS NULL "
                            "AND (expires_at IS NULL OR expires_at>?)", (name, now))
        return owner == "local" or privileged or all(row["owner"] == owner for row in rows)

    def revoke(self, name, now, *, owner="local", privileged=False):
        with self._tx() as conn:
            if not self._name_allowed(conn, name, now, owner, privileged):
                return None
            device = _device(conn.execute(f"SELECT * FROM devices WHERE name=? AND {_ACTIVE}", (name,)).fetchone())
            conn.execute("UPDATE devices SET revoked_at=? WHERE name=? AND revoked_at IS NULL", (now, name))
            return device

    def set_target(self, session_key, target: str | None):
        if not session_key:
            raise ValueError("a conversation identity is required")
        if target not in (None, "server") and self.device_by_id(target) is None:
            raise ValueError("device is not paired")
        with self._tx() as conn:
            conn.execute("DELETE FROM targets WHERE session_key=?", (session_key,))
            if target is not None:
                conn.execute("INSERT INTO targets VALUES(?,?,?)", (session_key, target, int(time.time())))

    def target(self, session_key) -> str | None:
        with self._tx() as conn:
            row = conn.execute("SELECT target FROM targets WHERE session_key=?", (session_key,)).fetchone()
            return row[0] if row else None

    def default_for(self, session_key, target):
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO session_defaults VALUES(?,?)", (session_key, target))
            return conn.execute("SELECT target FROM session_defaults WHERE session_key=?", (session_key,)).fetchone()[0]

    def log(self, req):
        with self._tx() as conn:
            conn.execute("INSERT INTO requests(id,device_id,session_key,task_id,state,preview,created_at) "
                         "VALUES(?,?,?,?,?,?,?)", (req.id, req.device_id, req.session_key, req.task_id,
                         "queued", req.command[:120], int(time.time())))

    def running(self, request_id):
        with self._tx() as conn:
            conn.execute("UPDATE requests SET state='running' WHERE id=? AND state='queued'", (request_id,))

    def close(self, request_id, outcome, now):
        with self._tx() as conn:
            conn.execute("UPDATE requests SET state=?,finished_at=?,exit_code=?,reason=? WHERE id=?",
                         (outcome.state.value, now, outcome.exit_code, outcome.reason, request_id))

    def mark_stale_lost(self, now):
        with self._tx() as conn:
            conn.execute("UPDATE requests SET state='lost',finished_at=?,exit_code=255,reason='gateway restarted' "
                         "WHERE state IN ('queued','running')", (now,))

    def recent(self, limit, session_key=None):
        if limit < 0:
            raise ValueError("limit must not be negative")
        with self._tx() as conn:
            rows = conn.execute("SELECT * FROM requests WHERE (? IS NULL OR session_key=?) "
                                "ORDER BY created_at DESC,rowid DESC LIMIT ?", (session_key, session_key, limit))
            return [RequestRow(**(dict(row) | {"state": RequestState(row["state"])})) for row in rows]
