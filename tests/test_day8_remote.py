"""Measured remote matrix budgets and waits that allow core timeout outcomes."""
from contextlib import contextmanager
import json
import math
import socket
import sys
import time
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

import matrix_cases as cases
import run_matrix
from core_rig import Core, ROOT, Rig
from dirtside.model import MAX_OUTPUT_BYTES, PART_MAX
from dirtside.protocol import parse_chunk, verify

PROBE_BYTES = 2_796_204
RATE, RTT = 1_140_000, 0.7
MEASURED = dict(probe_bytes=PROBE_BYTES, probe_s=RTT + PROBE_BYTES / RATE, round_trip_s=RTT)
LINK = MEASURED | dict(bytes_per_second=RATE, timeout_s=151)


@pytest.mark.parametrize("args,options,expected", [
    ({}, {}, 90), ({"command": "true"}, {}, 90), ({"timeout": None}, {}, 90),
    ({"timeout": 0}, {}, 15), ({"timeout": 1}, {}, 16),
    ({"timeout": 120}, {}, 135), ({"timeout": 151}, {}, 166),
    ({"timeout": 1.5}, {}, 16.5), ({"timeout": 120}, {"wait": 2}, 135),
    ({}, {"wait": 7}, 7),
])
def test_core_call_wait_follows_carried_timeout(args, options, expected):
    core, calls, waits = Core.__new__(Core), [], []
    def result(wait):
        waits.append(wait)
        return {"exit_code": 124}
    def submit(method, **params):
        calls.append((method, params))
        return SimpleNamespace(result=result)
    core.submit = submit
    assert core.call("terminal", args=args, **options) == {"exit_code": 124}
    assert waits == [expected] and calls == [("terminal", {"args": args})]


def test_core_terminal_observes_timeout_outcome_instead_of_rig_exception():
    core = Core.__new__(Core)
    outcome = {"exit_code": 124, "output": "[Command timed out after 120s]"}
    def result(wait):
        if wait <= 120:
            raise TimeoutError("rig stopped waiting before core could report its timeout")
        assert wait == 135
        return outcome
    core.submit = lambda *args, **kwargs: SimpleNamespace(result=result)
    assert core.terminal("sleep 150", timeout=120) == outcome


@pytest.mark.parametrize("rate,rtt,size,expected", [
    (1_140_000, .7, MAX_OUTPUT_BYTES, 151),
    (4_160_000, .7, MAX_OUTPUT_BYTES, 120),
    (2_470_000, .7, MAX_OUTPUT_BYTES, 120),
    (1_000_000, .7, MAX_OUTPUT_BYTES, 167),
    (500_000, .7, MAX_OUTPUT_BYTES, 301),
    (100_000, .7, MAX_OUTPUT_BYTES, 1375),
    (4_160_000, 5, MAX_OUTPUT_BYTES, 203),
    (1000, .7, PART_MAX + 1, 4206),
])
def test_remote_flood_budget_arithmetic(rate, rtt, size, expected):
    assert cases.flood_budget(rate, rtt, size) == expected


def test_encoded_flood_counts_padding_per_part():
    assert cases.encoded_bytes(MAX_OUTPUT_BYTES) == 89_478_528
    assert cases.encoded_bytes(PART_MAX + 1) == 2_796_208


@pytest.mark.parametrize("rate,rtt", [
    (0, .7), (-1, .7), (float("nan"), .7), (float("inf"), .7),
    (RATE, -1), (RATE, float("nan")), (RATE, float("inf")),
])
def test_remote_budget_rejects_invalid_measurements(rate, rtt):
    with pytest.raises(ValueError, match="link measurement"):
        cases.flood_budget(rate, rtt)


def test_probe_posts_one_maximum_signed_part_through_configured_url(monkeypatch):
    key, sent = SigningKey.generate(), []
    cfg = SimpleNamespace(gateway_url="https://probe.invalid/base", device_id="1" * 32,
                          token="private-test-token", key=key)
    clock = iter([0, .1, 1, 1 + RTT, 2, 2 + MEASURED["probe_s"]])
    monkeypatch.setattr(cases, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    def post(path, content):
        assert path == "api/plugins/dirtside/device/chunk"
        env = verify(key.verify_key, json.loads(content), int(time.time()))
        part = parse_chunk(env.body)
        assert env.kind == "chunk" and env.sender == cfg.device_id
        assert part.id == "r_" + "0" * 24 and part.seq == 0
        assert len(content) <= PROBE_BYTES + 1024
        sent.append(len(part.data))
        return SimpleNamespace(status_code=410)
    @contextmanager
    def client(**options):
        assert options["base_url"] == cfg.gateway_url + "/" and options["trust_env"] is False
        assert options["headers"] == {"Authorization": "Bearer " + cfg.token}
        yield SimpleNamespace(post=post)
    monkeypatch.setattr(cases.httpx, "Client", client)
    measured = cases.probe_link(cfg)
    assert sent == [0, 0, PART_MAX]
    assert measured == pytest.approx(MEASURED)


@pytest.mark.parametrize("settles", [True, False])
def test_probe_retries_incoherent_samples_without_inventing_a_rate(monkeypatch, settles):
    key, sent = SigningKey.generate(), []
    cfg = SimpleNamespace(gateway_url="https://probe.invalid", device_id="1" * 32,
                          token="private-test-token", key=key)
    durations = [.1, .8, .2] * (1 if settles else 3)
    if settles:
        durations += [.1, .2, .8]
    clock = iter(t for i, duration in enumerate(durations) for t in (10 * i, 10 * i + duration))
    monkeypatch.setattr(cases, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    def post(path, content):
        assert path == "api/plugins/dirtside/device/chunk"
        envelope = verify(key.verify_key, json.loads(content), int(time.time()))
        assert envelope.kind == "chunk" and envelope.sender == cfg.device_id
        sent.append(len(parse_chunk(envelope.body).data))
        return SimpleNamespace(status_code=410)
    @contextmanager
    def client(**options):
        assert options["trust_env"] is False
        assert options["headers"] == {"Authorization": "Bearer " + cfg.token}
        yield SimpleNamespace(post=post)
    monkeypatch.setattr(cases.httpx, "Client", client)
    measured = cases.probe_link(cfg)
    upload, round_trip = (.8, .2) if settles else (.2, .8)
    assert measured == pytest.approx(dict(probe_bytes=PROBE_BYTES, probe_s=upload, round_trip_s=round_trip))
    assert sent == [0, 0, PART_MAX] * (2 if settles else 3)


@pytest.mark.parametrize("status", [200, 401, 413, 503])
def test_probe_requires_unknown_request_response(monkeypatch, status):
    cfg = SimpleNamespace(gateway_url="https://probe.invalid", device_id="1" * 32,
                          token="private-test-token", key=SigningKey.generate())
    @contextmanager
    def client(**options):
        yield SimpleNamespace(post=lambda *args, **kwargs: SimpleNamespace(status_code=status))
    monkeypatch.setattr(cases.httpx, "Client", client)
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        cases.probe_link(cfg)


def test_probe_remote_uses_device_worker_and_round_trip_adjusted_rate(tmp_path, monkeypatch):
    prefix = ["ssh", "device.invalid", "worker", "--device-worker", "/private/rehearsal"]
    rig = SimpleNamespace(device_command=prefix, device_home=tmp_path, device_env={"state": "private"})
    calls = []
    def run(command, **options):
        calls.append(command)
        assert options["cwd"] == tmp_path and options["env"] == rig.device_env
        assert options["capture_output"] and options["text"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(MEASURED), stderr="")
    monkeypatch.setattr(run_matrix.subprocess, "run", run)
    link = run_matrix.probe_remote(rig)
    assert calls == [[*prefix, "probe"]]
    assert link["timeout_s"] == 151 and link["bytes_per_second"] == pytest.approx(RATE)
    assert {key: link[key] for key in MEASURED} == MEASURED


@pytest.mark.parametrize("upload,round_trip,rate,timeout", [
    (.002, .005, 1_398_102_000, 120),
    (.005, .005, 559_240_800, 120),
    (.002, 0, 1_398_102_000, 120),
    (10.8, .38, PROBE_BYTES / (10.8 - .38), 523),
    (12.3, .42, PROBE_BYTES / (12.3 - .42), 594),
])
def test_probe_remote_accepts_fast_samples_and_preserves_remote_arithmetic(
        tmp_path, monkeypatch, upload, round_trip, rate, timeout):
    stats = dict(probe_bytes=PROBE_BYTES, probe_s=upload, round_trip_s=round_trip)
    rig = SimpleNamespace(device_command=["worker"], device_home=tmp_path, device_env={})
    monkeypatch.setattr(run_matrix.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(stats), stderr=""))
    link = run_matrix.probe_remote(rig)
    assert math.isfinite(link["bytes_per_second"]) and link["bytes_per_second"] > 0
    assert link["bytes_per_second"] == pytest.approx(rate) and link["timeout_s"] == timeout
    assert {key: link[key] for key in stats} == stats


@pytest.mark.parametrize("stats", [
    {}, MEASURED | {"extra": 1}, MEASURED | {"probe_bytes": 1},
    MEASURED | {"probe_bytes": float(PROBE_BYTES)}, MEASURED | {"probe_bytes": True},
    MEASURED | {"probe_s": 0}, MEASURED | {"probe_s": -1},
    MEASURED | {"probe_s": float("nan")}, MEASURED | {"probe_s": float("inf")},
    MEASURED | {"probe_s": -float("inf")}, MEASURED | {"probe_s": True}, MEASURED | {"probe_s": ".002"},
    MEASURED | {"round_trip_s": -1}, MEASURED | {"round_trip_s": float("nan")},
    MEASURED | {"round_trip_s": float("inf")}, MEASURED | {"round_trip_s": -float("inf")},
    MEASURED | {"round_trip_s": True}, MEASURED | {"round_trip_s": ".005"},
])
def test_probe_remote_refuses_invalid_worker_data(tmp_path, monkeypatch, stats):
    rig = SimpleNamespace(device_command=["worker"], device_home=tmp_path, device_env={})
    monkeypatch.setattr(run_matrix.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(stats), stderr=""))
    with pytest.raises(ValueError, match="link measurement"):
        run_matrix.probe_remote(rig)


def test_remote_run_probes_once_before_rows_and_preserves_failure_measurement(tmp_path, monkeypatch):
    events = []
    class Rig:
        def pair(self):
            events.append(("pair", self.name))
            return self
        def start_agent(self):
            events.append(("agent", self.name))
            return self
        def choose(self):
            return self
    @contextmanager
    def factory(root, **options):
        rig = Rig()
        rig.name = root.name
        events.append(("start", rig.name))
        try:
            yield rig
        finally:
            events.append(("stop", rig.name))
    def measure(rig):
        assert events[-1] == ("pair", "link-probe")
        events.append(("measure", rig.name))
        return LINK
    def check(rig):
        assert rig.link is LINK
        if rig.name == "output-flood":
            raise RuntimeError("owned flood failure")
        return "first row passed"
    monkeypatch.setattr(run_matrix, "probe_remote", measure, raising=False)
    evidence = tmp_path / "evidence"
    assert run_matrix.run_rows(tmp_path / "rigs", evidence,
                              (("first", check), ("output-flood", check)), factory,
                              url="https://probe.invalid") == 1
    assert events[:5] == [("start", "link-probe"), ("pair", "link-probe"),
                          ("measure", "link-probe"), ("stop", "link-probe"), ("start", "first")]
    assert events.count(("measure", "link-probe")) == 1
    assert ("agent", "link-probe") not in events and events[-1] == ("stop", "output-flood")
    assert "PASS link-probe" in (evidence / "link-probe.txt").read_text()
    transcript = (evidence / "output-flood.txt").read_text()
    assert "owned flood failure" in transcript
    assert '"timeout_s": 151' in transcript and '"bytes_per_second": 1140000' in transcript


def test_failed_probe_releases_rig_without_running_rows(tmp_path, monkeypatch):
    events = []
    @contextmanager
    def factory(root, **options):
        events.append(root.name)
        try:
            yield SimpleNamespace(pair=lambda: None)
        finally:
            events.append("closed")
    def fail(_):
        raise ValueError("invalid link measurement")
    monkeypatch.setattr(run_matrix, "probe_remote", fail, raising=False)
    evidence = tmp_path / "evidence"
    assert run_matrix.run_rows(tmp_path / "rigs", evidence,
                              (("not-run", lambda _: pytest.fail("probe failure must stop rows")),),
                              factory, url="https://probe.invalid") == 1
    assert events == ["link-probe", "closed"]
    assert "invalid link measurement" in (evidence / "link-probe.txt").read_text()


@pytest.mark.parametrize("link,timeout", [(None, 120), (LINK, 151)])
def test_output_flood_keeps_loopback_and_uses_remote_budget(monkeypatch, link, timeout):
    calls = []
    def terminal(command, **args):
        calls.append((command, args))
        return {"exit_code": 0, "output": "[Dirtside: output capped at 67108864 bytes on the device]"}
    rig = SimpleNamespace(core=SimpleNamespace(terminal=terminal), link=link)
    clock = iter([1, 11.5])
    monkeypatch.setattr(cases, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    detail = cases.output_flood(rig)
    assert calls == [("head -c 67174400 /dev/zero | tr '\\0' f", {"timeout": timeout})]
    if link is None:
        assert detail == "64 MB device cap reported, foreground view bounded, command finished"
    else:
        assert "1.140 MB/s" in detail and "151s" in detail and "10.50s" in detail


@pytest.mark.parametrize("result", [
    {"exit_code": 124, "output": "output capped at 67108864 bytes on the device"},
    {"exit_code": 0, "output": "missing cap notice"},
    {"exit_code": 0, "output": "x" * 60_000 + "output capped at 67108864 bytes on the device"},
])
def test_remote_flood_retains_all_existing_assertions(result):
    rig = SimpleNamespace(link=LINK, core=SimpleNamespace(terminal=lambda *args, **kwargs: result))
    with pytest.raises(AssertionError):
        cases.output_flood(rig)


@pytest.mark.slow
def test_remote_mode_worker_probe_and_flood_use_real_entry_points(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    prefix = [sys.executable, str(ROOT / "tools/run_matrix.py"),
              "--device-worker", str(tmp_path / "remote-worker")]
    evidence = tmp_path / "evidence"
    @contextmanager
    def factory(root, **options):
        # The real tunnel terminates HTTPS; keep that auth configuration over local test HTTP.
        with Rig(root, **(options | {"url": None})) as rig:
            rig.public_url = options["url"]
            yield rig
    result = run_matrix.run_rows(tmp_path / "rigs", evidence, (("output-flood", cases.output_flood),),
                                 rig_factory=factory, url=f"http://127.0.0.1:{port}", port=port, device_command=prefix)
    failure = evidence / ("output-flood.txt" if (evidence / "output-flood.txt").exists() else "link-probe.txt")
    assert result == 0, failure.read_text()
    probe = json.loads((evidence / "link-probe.txt").read_text().split("\n", 1)[1])
    assert probe["probe_bytes"] == PROBE_BYTES and probe["bytes_per_second"] > 0
    assert probe["timeout_s"] >= 120
    transcript = (evidence / "output-flood.txt").read_text()
    assert "MB/s" in transcript and "budget=" in transcript and "elapsed=" in transcript
    assert str(probe["timeout_s"]) + "s" in transcript
    with socket.socket() as listener:
        assert listener.connect_ex(("127.0.0.1", port)) != 0
