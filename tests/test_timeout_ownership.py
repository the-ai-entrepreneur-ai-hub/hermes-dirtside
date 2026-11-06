"""Deadline ordering must not change core's timeout or output contracts."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from nacl.signing import SigningKey
from tools.tool_output_limits import get_max_bytes

from dirtside.agent import loop
from dirtside.environment import DirtsideEnvironment
from dirtside.model import MAX_OUTPUT_BYTES, Outcome, Policy, RequestState, device_timeout_s
from dirtside.protocol import WireExec
from test_environment import device_setup
from test_executor import alive, execute
from test_registry import request


def environment(root):
    relay, device, fake = device_setup(root)
    with fake:
        env = DirtsideEnvironment(relay, device, "chat", "default", "~", 120)
    return relay, device, env


@pytest.mark.parametrize("device_first", [False, True])
@pytest.mark.parametrize("data", [b"", b"partial"])
def test_timeout_order_has_identical_rendering(tmp_path, device_first, data):
    relay, device, env = environment(tmp_path)
    handle = relay.submit(request(device))
    assert relay.feed(handle.req.id, 0, data)
    if device_first:
        assert relay.close(handle.req.id, Outcome(RequestState.FINISHED, 124, 1, False, "command timed out"))
        assert handle.poll() == handle.wait(0) == 124
    result = env._wait_for_process(handle, timeout=1)
    assert result == {"output": (data.decode() + "\n[Command timed out after 1s]").lstrip("\n"),
                      "returncode": 124, "hermes_timed_out": True}


def test_device_timeout_preserves_bounded_capture_and_spill(tmp_path):
    relay, device, env = environment(tmp_path)
    handle = relay.submit(request(device))
    data = "head\n" + "地" * 100000 + "\ntail"
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(env._wait_for_process, handle, timeout=1, bounded_capture=True)
        assert relay.feed(handle.req.id, 0, data.encode())
        assert relay.close(handle.req.id, Outcome(RequestState.FINISHED, 124, 1, False, "command timed out"))
        result = future.result(10)
    assert result["returncode"] == 124 and result["hermes_timed_out"] is True
    assert result["output"].startswith("head\n")
    assert result["output"].endswith("\ntail\n[Command timed out after 1s]")
    assert result["output"].count("[Command timed out") == 1
    assert len(result["output"]) <= get_max_bytes()
    assert result["output_total_chars"] == len(data)
    assert Path(result["full_output_path"]).read_text() == data


@pytest.mark.parametrize("state,code,reason,truncated,notice", [
    (RequestState.FINISHED, 124, "", False, ""),
    (RequestState.FINISHED, 124, "command timed out elsewhere", False, "\n[Dirtside: command timed out elsewhere]"),
    (RequestState.FINISHED, 0, "command timed out", False, "\n[Dirtside: command timed out]"),
    (RequestState.LOST, 255, "command timed out", False, "\n[Dirtside: command timed out]"),
    (RequestState.CANCELLED, 130, "command cancelled", False, "\n[Dirtside: command cancelled]"),
    (RequestState.REFUSED, 126, "command matches deny pattern", False,
     "\n[Dirtside: command matches deny pattern]"),
    (RequestState.FINISHED, 124, "output capped at 1000 bytes on the device", True,
     "\n[Dirtside: output capped at 1000 bytes on the device]"),
])
def test_other_terminal_outcomes_are_not_timeouts(tmp_path, state, code, reason, truncated, notice):
    relay, device, env = environment(tmp_path)
    handle = relay.submit(request(device))
    assert relay.feed(handle.req.id, 0, b"partial")
    assert relay.close(handle.req.id, Outcome(state, code, 1, truncated, reason))
    assert env._wait_for_process(handle, timeout=1) == {"output": "partial" + notice, "returncode": code}


def test_device_timeout_also_reports_output_cap(tmp_path):
    relay, device, env = environment(tmp_path)
    handle = relay.submit(request(device))
    assert relay.feed(handle.req.id, 0, b"x" * 1000)
    assert relay.close(handle.req.id, Outcome(
        RequestState.FINISHED, 124, 1, True, "command timed out; output capped at 1000 bytes on the device"))
    result = env._wait_for_process(handle, timeout=1)
    assert result == {"output": "x" * 1000 + "\n[Command timed out after 1s]"
                      "\n[Dirtside: output capped at 1000 bytes on the device]",
                      "returncode": 124, "hermes_timed_out": True}


@pytest.mark.parametrize("requested,cap,expected", [(1, 900, 2), (10, 1, 1), (900, 900, 900),
                                                   (899, 900, 900), (120, 60, 60)])
def test_backstop_duration_is_policy_capped(requested, cap, expected):
    assert device_timeout_s(requested, Policy((), cap, MAX_OUTPUT_BYTES, 1)) == expected


@pytest.mark.parametrize("requested,cap,expected", [(1, 900, 2), (10, 1, 1)])
def test_device_backstop_without_gateway(tmp_path, requested, cap, expected):
    out, data = execute(tmp_path, "echo $$ > pid; printf partial; sleep 60",
                        timeout=requested, policy=Policy((), cap, MAX_OUTPUT_BYTES, 1))
    assert out.exit_code == 124 and out.reason == "command timed out" and data == b"partial"
    assert out.duration_ms >= expected * 1000
    assert not alive(int((tmp_path / "pid").read_text()))


@pytest.mark.parametrize("cap,attempts", [(900, [2, 1]), (1, [1])])
def test_agent_upload_budget_preserves_timeout_and_cap(tmp_path, monkeypatch, cap, attempts):
    clock, observed, results = [100.0], [], []
    monkeypatch.setattr(loop, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    class Cancel:
        def is_set(self):
            return False
        def wait(self, seconds):
            clock[0] += seconds
    def respond(req):
        if req.url.path.endswith("/chunk"):
            observed.append(req.extensions["timeout"]["read"])
            return httpx.Response(503)
        results.append(json.loads(req.content)["body"])
        return httpx.Response(200)
    def rejected(req, policy, send, *, cancel):
        assert not send(0, b"partial")
        return Outcome(RequestState.FINISHED, 130, 0, True,
                       "gateway no longer accepts output; output capped at 1000 bytes on the device"), None
    monkeypatch.setattr(loop, "run", rejected)
    cfg = SimpleNamespace(policy=Policy((), cap, 1000, 1), key=SigningKey.generate(), device_id="01" * 16)
    req = WireExec("r_" + "02" * 12, "sleep 60", "sleep 60", False, 1, None, str(tmp_path))
    with httpx.Client(transport=httpx.MockTransport(respond), base_url="http://127.0.0.1") as client:
        agent = loop._Agent(cfg, client, threading.Event(), SimpleNamespace(write=lambda *a, **k: None))
        try:
            agent.execute(req, Cancel())
        finally:
            agent.pool.shutdown(wait=True)
    assert observed == attempts
    assert len(results) == 1 and results[0]["exit_code"] == 124 and results[0]["truncated"] is True
    assert results[0]["reason"] == "command timed out; output capped at 1000 bytes on the device"
