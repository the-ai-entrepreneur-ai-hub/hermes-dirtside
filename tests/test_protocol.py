"""Protocol contracts at the signed JSON boundary."""
import base64
import copy
import time

import pytest
from nacl.signing import SigningKey

from dirtside.model import CHUNK_BYTES, RequestState
from dirtside.protocol import (
    ProtocolError, ReplayGuard, canonical, parse_chunk, parse_exec,
    parse_hello, parse_poll, parse_result, sign, verify,
)

RID = "r_" + "12" * 12


def hello_body():
    return dict(pubkey=base64.b64encode(bytes(SigningKey.generate().verify_key)).decode(),
                name="macbook", os="macOS", arch="arm64", home="/home/device",
                temp_dir="/tmp", agent_version="0.1.0")


def exec_body():
    return dict(id=RID, command="pwd", script="pwd", login=False,
                timeout_s=120, stdin=None, cwd="/tmp")


def result_body():
    return dict(id=RID, state="finished", exit_code=0, duration_ms=4, truncated=False, reason="")


def signed_fields(key, **changes):
    wire = sign(key, "exec", "relay", exec_body()) | changes
    wire["sig"] = base64.b64encode(key.sign(canonical({k: v for k, v in wire.items() if k != "sig"})).signature).decode()
    return wire


def test_envelope_roundtrip():
    key = SigningKey.generate()
    wire = sign(key, "exec", "relay", exec_body())
    env = verify(key.verify_key, wire, int(time.time()))
    assert env.body == exec_body()
    assert len(env.sig) == 64
    for field, bad in (("sender", "other"), ("kind", "poll"), ("body", {}), ("ts", wire["ts"] - 1)):
        with pytest.raises(ProtocolError):
            verify(key.verify_key, wire | {field: bad}, int(time.time()))
    with pytest.raises(ProtocolError):
        verify(SigningKey.generate().verify_key, wire, int(time.time()))


def test_canonical_stable():
    assert canonical({"b": [2, "地"], "a": 1}) == b'{"a":1,"b":[2,"\xe5\x9c\xb0"]}'
    assert canonical({"a": 1, "b": {"y": 2, "x": 3}}) == canonical({"b": {"x": 3, "y": 2}, "a": 1})


def test_replay_guard():
    key = SigningKey.generate()
    wire = sign(key, "exec", "relay", exec_body())
    now, guard = int(time.time()), ReplayGuard()
    verify(key.verify_key, wire, now, guard)
    with pytest.raises(ProtocolError, match="replayed"):
        verify(key.verify_key, wire, now, guard)
    assert verify(key.verify_key, wire, now).body == exec_body()
    guard.check("different-sender", wire["nonce"], now)
    guard.check("relay", wire["nonce"], now + 301)
    for n in range(4097):
        guard.check("relay", str(n), now + 301)
    assert len(guard._seen) == 4096
    guard.check("relay", "0", now + 301)


@pytest.mark.parametrize("changes", [
    {"v": 2}, {"v": True}, {"ts": True}, {"ts": 0}, {"nonce": "bad"},
    {"sender": ""}, {"kind": "unknown"}, {"body": []},
])
def test_bad_envelope(changes):
    key = SigningKey.generate()
    with pytest.raises(ProtocolError):
        verify(key.verify_key, signed_fields(key, **changes), int(time.time()))


def test_bad_signature_does_not_poison_replay():
    key, guard = SigningKey.generate(), ReplayGuard()
    wire = sign(key, "poll", "relay", {})
    with pytest.raises(ProtocolError):
        verify(key.verify_key, wire | {"sig": base64.b64encode(b"x" * 64).decode()}, int(time.time()), guard)
    assert verify(key.verify_key, wire, int(time.time()), guard)


@pytest.mark.parametrize("bad", [None, [], {}, "wire", {"sig": "!"}])
def test_envelope_wrong_shape(bad):
    with pytest.raises(ProtocolError):
        verify(SigningKey.generate().verify_key, bad, int(time.time()))


@pytest.mark.parametrize("parser,body", [
    (parse_hello, hello_body()),
    (parse_exec, exec_body()),
    (parse_chunk, dict(id=RID, seq=0, data="YWJj")),
    (parse_result, result_body()),
    (parse_poll, dict(exec=exec_body(), cancel=[RID])),
])
def test_wire_bodies(parser, body):
    assert parser(body)
    for bad in (None, [], {}, body | {"extra": True}):
        if parser is parse_poll and bad == {}:
            assert parser(bad) == (None, [])
            continue
        with pytest.raises(ProtocolError):
            parser(bad)
    for field in body:
        if parser is parse_poll:
            continue
        bad = {k: v for k, v in body.items() if k != field}
        with pytest.raises(ProtocolError):
            parser(bad)
        with pytest.raises(ProtocolError):
            parser(body | {field: []})


@pytest.mark.parametrize("parser,base,changes", [
    (parse_exec, exec_body(), {"timeout_s": True}),
    (parse_exec, exec_body(), {"timeout_s": 0}),
    (parse_exec, exec_body(), {"login": 1}),
    (parse_exec, exec_body(), {"cwd": "relative"}),
    (parse_exec, exec_body(), {"script": "bad\0script"}),
    (parse_chunk, dict(id=RID, seq=0, data=""), {"seq": -1}),
    (parse_chunk, dict(id=RID, seq=0, data=""), {"seq": True}),
    (parse_chunk, dict(id=RID, seq=0, data=""), {"id": "other"}),
    (parse_chunk, dict(id=RID, seq=0, data=""), {"data": "!"}),
    (parse_result, result_body(), {"exit_code": True}),
    (parse_result, result_body(), {"duration_ms": -1}),
    (parse_result, result_body(), {"truncated": 1}),
    (parse_result, result_body(), {"state": "lost"}),
    (parse_hello, hello_body(), {"pubkey": "YQ=="}),
    (parse_hello, hello_body(), {"name": "../device"}),
    (parse_hello, hello_body(), {"home": "~"}),
    (parse_poll, {}, {"cancel": [True]}),
    (parse_poll, {}, {"cancel": RID}),
])
def test_wire_invalid_values(parser, base, changes):
    with pytest.raises(ProtocolError):
        parser(base | changes)


def test_parse_result():
    out, tail = parse_result(result_body())
    assert out.state is RequestState.FINISHED and tail is None
    out, tail = parse_result(result_body() | {"seq": 2, "data": "AP+A"})
    assert tail.id == RID and tail.seq == 2 and tail.data == b"\0\xff\x80"
    assert parse_result(result_body() | {"state": "refused", "exit_code": 126})[0].state is RequestState.REFUSED
    for change in ({"seq": 2}, {"data": "YQ=="}, {"seq": -1, "data": ""}):
        with pytest.raises(ProtocolError):
            parse_result(result_body() | change)
    too_big = base64.b64encode(b"x" * (CHUNK_BYTES + 1)).decode()
    with pytest.raises(ProtocolError):
        parse_result(result_body() | {"seq": 0, "data": too_big})
    wire = copy.deepcopy(exec_body())
    wire["stdin"] = "text without newline"
    assert parse_exec(wire).stdin == wire["stdin"]
