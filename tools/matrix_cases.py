"""The plan's eight reliability rows through an installed, gated core rig."""
import base64
import re
import time

import httpx
from nacl.signing import SigningKey, VerifyKey

from core_rig import until
from dirtside.protocol import canonical, sign, verify


def running(rig, preview):
    return next((row for row in rig.core.http("GET", "/requests").json()
                 if row["preview"] == preview and row["state"] == "running" and row["tail"]), None)


def gone(rig, pid):
    result = rig.core.terminal(f"if kill -0 {int(pid)} 2>/dev/null; then printf alive; else printf gone; fi")
    return result["output"] == "gone"


def begin(rig, label, timeout=90):
    command = f"printf '{label}:%s\\n' $$; while :; do printf tick; sleep 1; done"
    future = rig.core.submit("terminal", session="chat", args=dict(command=command, timeout=timeout))
    row = until(lambda: running(rig, command), timeout=10)
    pid = int(re.search(re.escape(label) + r":(\d+)", row["tail"])[1])
    return future, row, pid


def reporting_loss(rig):
    # Verify a normal terminal timeout too, before cutting the reporting channel.
    timed = rig.core.terminal("printf timeout-check; sleep 5", timeout=1)
    assert timed["exit_code"] == 124 and "timeout-check" in timed["output"], timed
    future, row, pid = begin(rig, "matrix-loss")
    started = time.monotonic()
    rig.core.call("network", blocked=True)
    try:
        result = future.result(58)
        elapsed = time.monotonic() - started
        assert result["exit_code"] == 124 and "matrix-loss" in result["output"], result
        assert 44 <= elapsed < 57, elapsed
        ended = next(r for r in rig.core.http("GET", "/requests").json() if r["id"] == row["id"])
        assert ended["state"] == "lost" and ended["reason"] == "device stopped reporting", ended
    finally:
        rig.core.call("network", blocked=False)
    until(rig.online, timeout=35)
    until(lambda: gone(rig, pid), timeout=12)
    return f"lost exit=124, partial retained, {elapsed:.2f}s, reconnect stopped the old group"


def gateway_restart(rig):
    future, row, pid = begin(rig, "matrix-restart")
    identity = rig.core.http("GET", "/devices").json()[0]["id"]
    rig.restart_gateway()
    try:
        future.result(1)
    except RuntimeError:
        pass
    else:
        raise AssertionError("the old gateway tool call survived process death")
    until(rig.online, timeout=40)
    old = next(r for r in rig.core.http("GET", "/requests").json() if r["id"] == row["id"])
    assert old["state"] == "lost", old
    until(lambda: gone(rig, pid), timeout=12)
    assert any(d["id"] == identity for d in rig.core.http("GET", "/devices").json())
    assert rig.core.terminal("printf restarted")["output"] == "restarted"
    return "gateway process replaced, stale work lost, old group stopped, pairing reused"


def device_restart(rig):
    identity = rig.core.http("GET", "/devices").json()[0]["id"]
    old_pid = rig.agent.pid
    rig.stop_agent()
    rig.start_agent()
    assert rig.agent.pid != old_pid
    assert rig.core.terminal("printf reconnected")["output"] == "reconnected"
    assert any(d["id"] == identity for d in rig.core.http("GET", "/devices").json())
    return "device process replaced, fresh poll observed, pairing reused"


def concurrent_commands(rig):
    assert rig.core.terminal("true")["exit_code"] == 0
    futures = [rig.core.submit("terminal", session="chat", task_id=f"child-{n}",
                              args=dict(command=f"printf concurrent-{n}; sleep 2")) for n in range(2)]
    until(lambda: sum(r["state"] == "running" and r["preview"].startswith("printf concurrent-")
                      for r in rig.core.http("GET", "/requests").json()) == 2)
    results = [future.result(8) for future in futures]
    assert [r["output"] for r in results] == ["concurrent-0", "concurrent-1"]
    assert all(r["exit_code"] == 0 for r in results)
    keys = [rig.core.call("state", session="chat", task_id=f"child-{n}")["key"] for n in range(2)]
    assert keys == ["session:chat", "session:chat"], keys
    return "two calls overlapped, exact outputs, core shares one session environment"


def probe(rig, skew=0):
    name, key = "clock-probe", SigningKey.generate()
    code = rig.core.http("POST", "/pairing", json={"name": name}).json()["code"]
    hello = dict(pubkey=base64.b64encode(bytes(key.verify_key)).decode(), name=name, os="probe",
                 arch="probe", home="/tmp", temp_dir="/tmp", agent_version="0.1.0")
    wire = sign(key, "hello", name, hello)
    wire["ts"] += skew
    wire["sig"] = base64.b64encode(key.sign(canonical({k: v for k, v in wire.items() if k != "sig"})).signature).decode()
    with httpx.Client(base_url=rig.public_url.rstrip("/") + "/", timeout=35, trust_env=False) as client:
        response = client.post("api/plugins/dirtside/device/pair", json=wire,
                               headers={"Authorization": "Bearer " + code})
    return response, key


def clock_skew(rig):
    for skew in (-601, 601):
        response, _ = probe(rig, skew)
        assert response.status_code == 400, response.status_code
    assert not any(d["name"] == "clock-probe" for d in rig.core.http("GET", "/devices").json())
    return "correctly signed hello at -601s and +601s rejected with 400 before pairing"


def output_flood(rig):
    result = rig.core.terminal("head -c 67174400 /dev/zero | tr '\\0' f", timeout=120)
    assert result["exit_code"] == 0, result["exit_code"]
    assert "output capped at 67108864 bytes on the device" in result["output"]
    assert len(result["output"]) < 60_000, len(result["output"])
    return "64 MB device cap reported, foreground view bounded, command finished"


def long_poll(rig):
    paired, key = probe(rig)
    assert paired.status_code == 200, paired.status_code
    cfg = paired.json()
    headers = {"Authorization": "Bearer " + cfg["token"]}
    wire = sign(key, "poll", cfg["device_id"], {})
    started = time.monotonic()
    with httpx.Client(base_url=rig.public_url.rstrip("/") + "/", timeout=35, trust_env=False) as client:
        response = client.post("api/plugins/dirtside/device/poll", json=wire, headers=headers)
    elapsed = time.monotonic() - started
    assert response.status_code == 200 and 24 <= elapsed < 33, (response.status_code, elapsed)
    env = verify(VerifyKey(base64.b64decode(cfg["relay_pubkey"])), response.json(), int(time.time()))
    assert env.body == {"cancel": []}, env.body
    return f"empty signed heartbeat after {elapsed:.2f}s through the configured URL"


def interrupt(rig):
    future, _, pid = begin(rig, "matrix-interrupt")
    started = time.monotonic()
    rig.core.call("interrupt", call_id=future.call_id)
    result = future.result(3)
    elapsed = time.monotonic() - started
    assert result["exit_code"] == 130 and "matrix-interrupt" in result["output"], result
    until(lambda: gone(rig, pid), timeout=5)
    assert time.monotonic() - started < 5
    return f"core interrupt exit=130 in {elapsed:.3f}s, partial retained, group stopped"


ROWS = (
    ("device-loses-network", reporting_loss), ("gateway-restarts", gateway_restart),
    ("device-restarts", device_restart), ("concurrent-commands", concurrent_commands),
    ("clock-skew", clock_skew), ("output-flood", output_flood),
    ("long-poll", long_poll), ("user-interrupt", interrupt),
)
