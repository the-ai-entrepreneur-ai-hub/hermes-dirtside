"""The benchmark keeps exact threshold boundaries and rejects every miss."""
import os
import subprocess
import sys

import pytest

from bench import percentile, report, timed
from core_rig import CORE, ROOT


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


def test_benchmark_loopback_smoke():
    result = subprocess.run([sys.executable, str(ROOT / "tools/bench.py"), "--loopback"],
                            env=os.environ | {"HERMES_SRC": str(CORE)}, cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("| PASS |") == 4
    assert "50 paired pwd" in result.stdout and "10,000,000 verified bytes" in result.stdout
