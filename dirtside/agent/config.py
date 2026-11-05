"""Private device configuration, resolved in the device's selected Hermes home."""
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from hermes_constants import get_hermes_home
from nacl.signing import SigningKey, VerifyKey
from ..model import MAX_OUTPUT_BYTES, Policy
DEFAULT_DENY = (r"\bsudo\b", r"rm\s+-rf\s+/(?:\s|$)", r"\bmkfs\b", r"\bdd\s+if=",
                r"\b(?:shutdown|reboot)\b", r"launchctl\s+unload",
                r"systemctl\b.*\b(?:stop|disable)\b", r":\(\)\s*\{", r"curl\b.*\|\s*(?:ba)?sh")
def device_path():
    return get_hermes_home() / "dirtside" / "device.json"
def gateway_url(value):
    url = urlsplit(value)
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("invalid gateway port")
    local = url.scheme == "http" and url.hostname in {"127.0.0.1", "::1", "localhost"}
    if not (url.scheme == "https" or local) or not url.hostname or url.username or url.password:
        raise ValueError("gateway URL must use HTTPS, or HTTP on loopback")
    if url.query or url.fragment:
        raise ValueError("gateway URL cannot contain a query or fragment")
    return value.rstrip("/")
def policy_data(policy):
    return dict(deny_patterns=[p.pattern for p in policy.deny_patterns], max_timeout_s=policy.max_timeout_s,
                max_output_bytes=policy.max_output_bytes, max_parallel=policy.max_parallel)
def parse_policy(data):
    if type(data) is not dict or set(data) != {"deny_patterns", "max_timeout_s", "max_output_bytes", "max_parallel"}:
        raise ValueError("invalid device policy")
    patterns = data["deny_patterns"]
    if type(patterns) is not list or not all(type(p) is str for p in patterns):
        raise ValueError("deny patterns must be strings")
    caps = [data[k] for k in ("max_timeout_s", "max_output_bytes", "max_parallel")]
    if not all(type(n) is int and n > 0 for n in caps):
        raise ValueError("policy caps must be positive integers")
    try:
        return Policy(tuple(re.compile(p) for p in patterns), *caps)
    except re.error as exc:
        raise ValueError("invalid deny pattern") from exc
def default_policy():
    return Policy(tuple(re.compile(p) for p in DEFAULT_DENY), 900, MAX_OUTPUT_BYTES, 4)
@dataclass(frozen=True)
class DeviceConfig:
    gateway_url: str
    device_id: str
    token: str = field(repr=False)
    key: SigningKey = field(repr=False)
    relay_pubkey: VerifyKey
    name: str
    policy: Policy
    def __post_init__(self):
        gateway_url(self.gateway_url)
        if not re.fullmatch(r"[0-9a-f]{32}", self.device_id) or not re.fullmatch(r"[a-z0-9-]{1,32}", self.name):
            raise ValueError("invalid device identity")
        if type(self.token) is not str or not self.token or not isinstance(self.key, SigningKey):
            raise ValueError("invalid device credentials")
        if not isinstance(self.relay_pubkey, VerifyKey):
            raise ValueError("invalid relay public key")
        parse_policy(policy_data(self.policy))
    @classmethod
    def load(cls, path=None):
        fd = os.open(path or device_path(), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError("device config must be a private regular file")
            data = json.load(stream)
        return cls(**(data | dict(key=SigningKey(bytes.fromhex(data["key"])),
                                 relay_pubkey=VerifyKey(bytes.fromhex(data["relay_pubkey"])),
                                 policy=parse_policy(data["policy"]))))
    def save(self, path=None):
        path = Path(path or device_path())
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        data = self.__dict__ | dict(key=bytes(self.key).hex(), relay_pubkey=bytes(self.relay_pubkey).hex(),
                                   policy=policy_data(self.policy))
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".device-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
