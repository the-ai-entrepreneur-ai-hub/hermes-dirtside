"""Immutable domain records and fixed protocol limits."""
import re
from dataclasses import dataclass
from enum import Enum
from typing import NewType

DeviceId = NewType("DeviceId", str)
SessionKey = NewType("SessionKey", str)
RequestId = NewType("RequestId", str)

@dataclass(frozen=True)
class Device:
    id: DeviceId
    name: str
    pubkey: bytes
    os: str
    arch: str
    home: str
    temp_dir: str
    agent_version: str

@dataclass(frozen=True)
class Pending:
    name: str
    expires_at: int

Credential = Pending | Device

@dataclass(frozen=True)
class Server:
    pass

@dataclass(frozen=True)
class OnDevice:
    device: Device

Target = Server | OnDevice

class RequestState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    LOST = "lost"

TERMINAL = frozenset({RequestState.FINISHED, RequestState.REFUSED, RequestState.CANCELLED, RequestState.LOST})

@dataclass(frozen=True)
class ExecRequest:
    id: RequestId
    device_id: DeviceId
    session_key: SessionKey
    task_id: str
    command: str
    script: str
    login: bool
    timeout_s: int
    stdin: str | None
    cwd: str

@dataclass(frozen=True)
class Outcome:
    state: RequestState
    exit_code: int
    duration_ms: int
    truncated: bool
    reason: str

@dataclass(frozen=True)
class Policy:
    deny_patterns: tuple[re.Pattern, ...]
    max_timeout_s: int
    max_output_bytes: int
    max_parallel: int

@dataclass(frozen=True)
class Refused:
    reason: str

Decision = None | Refused

@dataclass(frozen=True)
class RequestRow:
    id: RequestId
    device_id: DeviceId
    session_key: SessionKey
    task_id: str
    state: RequestState
    preview: str
    created_at: int
    finished_at: int | None
    exit_code: int | None
    reason: str | None

OFFLINE_AFTER_S = 45
LOST_GRACE_S = 5
POLL_HOLD_S = 25
PAIR_TTL_S = 600
CHUNK_BYTES = 65536
FLUSH_MS = 200
FEED_BLOCK_S = 10
PANE_TAIL_BYTES = 4096
MAX_OUTPUT_BYTES = 64 << 20
