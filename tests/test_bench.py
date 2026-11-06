"""Strict threshold checks and report-only benchmark smoke."""
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from bench import cancellation, percentile, report, timed
from core_rig import CORE, ROOT
from dirtside.model import RequestState


def test_nearest_rank_does_not_drop_slow_samples():
    samples = list(range(1, 51))
    assert percentile(samples, .5) == 25
    assert percentile(samples, .95) == 48
    assert percentile([10, 1, 5], .5) == 5


@pytest.mark.parametrize("metrics,exit_code", [
    ((15, 40, 8, 50), 0),
    ((15.001, 40, 8, 50), 1),
    ((15, 40.001, 8, 50), 1),
    ((15, 40, 7.999, 50), 1),
    ((15, 40, 8, 50.001), 1),
])
def test_each_threshold_and_exact_boundaries(capsys, metrics, exit_code):
    assert report(metrics) == exit_code
    text = capsys.readouterr().out
    assert text.startswith("| Measurement |")
    assert ("FAIL" in text) == bool(exit_code)
    assert text.count("PASS") == (3 if exit_code else 4)


def test_failed_command_is_not_a_latency_sample():
    class Failed:
        def execute(self, command, **options):
            assert options == {"bounded_capture": False}
            return {"returncode": 1, "output": "error"}
    with pytest.raises(RuntimeError, match="command failed"):
        timed(Failed(), "pwd")


def test_cancellation_starts_at_claim_without_waiting_for_output():
    killed = threading.Event()
    handle = SimpleNamespace(state=RequestState.QUEUED, req=SimpleNamespace(id="bench"), kill=killed.set)
    def execute(command, **options):
        assert command == "head -c 65536 /dev/zero; sleep 30" and options == {"timeout": 10}
        handle.state = RequestState.RUNNING
        assert killed.wait(2)
        return {"returncode": 130}
    def tail(_):
        pytest.fail("the kill benchmark must not wait for first output")
    relay = SimpleNamespace(_condition=threading.Condition(), handles={"bench": handle}, tail=tail)
    assert cancellation(SimpleNamespace(execute=execute), relay) >= 0
    assert killed.is_set()


def test_benchmark_loopback_smoke():
    result = subprocess.run([sys.executable, str(ROOT / "tools/bench.py"), "--loopback", "--report-only"],
                            env=os.environ | {"HERMES_SRC": str(CORE)}, cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(
        "Signed in-process loopback; 50 paired pwd samples; 10,000,000 verified bytes; excludes HTTP/LAN.\n")
    rows = [line.split("|")[1].strip() for line in result.stdout.splitlines() if line.startswith("| ")]
    assert rows == ["Measurement", "pwd added p50", "pwd added p95", "10 MB output", "kill to tool return",
                    "pwd client added p50", "pwd client added p95"]
    assert result.stdout.count("| report only | INFO |") == 2


def test_benchmark_smoke_accepts_a_reported_timing_miss(monkeypatch, capsys):
    from bench_client import report as report_client
    assert report((15, 40, 7.96, 50), report_only=True) == 0
    report_client((1, 2))
    output = ("Signed in-process loopback; 50 paired pwd samples; 10,000,000 verified bytes; excludes HTTP/LAN.\n"
              + capsys.readouterr().out)
    assert "| 10 MB output | 7.96 MB/s | >= 8 MB/s | FAIL |" in output
    def run(command, **options):
        assert command == [sys.executable, str(ROOT / "tools/bench.py"), "--loopback", "--report-only"]
        assert options["cwd"] == ROOT and options["capture_output"] and options["text"]
        return SimpleNamespace(returncode=0, stdout=output, stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    test_benchmark_loopback_smoke()
