"""The matrix must retain failures, continue, and release owned resources."""
from contextlib import contextmanager
import json
import os
import re
import socket
import subprocess
import sys

import pytest
from core_rig import ROOT, Rig, install, stop_process, until
from run_matrix import main, run_rows


def test_matrix_records_failure_and_releases_every_rig(tmp_path, capsys):
    events = []
    class Probe:
        def pair(self):
            return self
        start_agent = choose = pair
    @contextmanager
    def factory(root, **_):
        events.append(("start", root.name))
        try:
            yield Probe()
        finally:
            events.append(("stop", root.name))
    def fail(_):
        raise RuntimeError("owned failure")
    def pass_(_):
        return "next row still ran"
    evidence = tmp_path / "evidence"
    assert run_rows(tmp_path, evidence, (("bad", fail), ("good", pass_)), factory) == 1
    assert events == [("start", "bad"), ("stop", "bad"), ("start", "good"), ("stop", "good")]
    assert "FAIL bad" in (evidence / "bad.txt").read_text()
    assert "owned failure" in (evidence / "bad.txt").read_text()
    assert "next row still ran" in (evidence / "good.txt").read_text()
    assert "Matrix: 1/2 passed" in capsys.readouterr().out


def test_matrix_requires_explicit_execution_mode(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--evidence", str(tmp_path)])
    assert error.value.code == 2
    with pytest.raises(SystemExit) as error:
        main(["--loopback", "--gateway-url", "https://example.test"])
    assert error.value.code == 2


@pytest.mark.slow
@pytest.mark.parametrize("with_pythonpath", [True, False])
def test_owned_device_worker_uses_private_state_and_stops_on_eof(tmp_path, with_pythonpath):
    state = tmp_path / "worker"
    prefix = [sys.executable, str(ROOT / "tools/run_matrix.py"), "--device-worker", str(state)]
    if not with_pythonpath:
        prefix = ["env", "-u", "PYTHONPATH", *prefix]
    with Rig(tmp_path / "rig", device_command=prefix) as rig:
        rig.pair().start_agent().choose()
        assert rig.core.terminal("pwd")["output"] == str(state / "user")
        agent, gateway, port = rig.agent, rig.core.proc, rig.core.info["port"]
    assert agent.poll() == 0 and gateway.poll() == 0
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.slow
def test_real_matrix_failure_stops_active_command_and_both_processes(tmp_path):
    owned = []
    def fail(rig):
        command = "printf 'cleanup:%s' $$; while :; do sleep 1; done"
        rig.core.submit("terminal", session="chat", args={"command": command})
        def active():
            return next((r for r in rig.core.http("GET", "/requests").json() if "cleanup:" in r["tail"]), None)
        row = until(active)
        pid = int(re.search(r"cleanup:(\d+)", row["tail"])[1])
        owned.extend((rig.agent, rig.core.proc, pid, rig.core.info["port"]))
        raise RuntimeError("owned active-command failure")
    assert run_rows(tmp_path / "rigs", tmp_path / "evidence", (("failure", fail),)) == 1
    agent, gateway, pid, port = owned
    assert agent.poll() is not None and gateway.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.slow
def test_matrix_sigterm_releases_owned_processes_and_command(tmp_path):
    marker = tmp_path / "owned.json"
    program = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'tools')!r})
import run_matrix
from matrix_cases import begin
original = run_matrix.run_rows
def check(rig):
    future, _, pid = begin(rig, "signal-cleanup")
    path = Path({str(marker)!r})
    path.with_suffix(".tmp").write_text(json.dumps([rig.agent.pid, rig.core.proc.pid, pid, rig.core.info["port"]]))
    path.with_suffix(".tmp").replace(path)
    future.result(90)
def rows(root, evidence, **options):
    return original(root, evidence, (("signal", check),), **options)
run_matrix.run_rows = rows
raise SystemExit(run_matrix.main(["--loopback", "--evidence", {str(tmp_path / 'evidence')!r}]))
"""
    with (tmp_path / "controller.log").open("w") as log:
        proc = subprocess.Popen([sys.executable, "-c", program], cwd=ROOT,
                                env=install(tmp_path / "controller"), stdout=log, stderr=log)
        try:
            until(marker.exists, timeout=20)
            *pids, port = json.loads(marker.read_text())
            proc.terminate()
            assert proc.wait(25) == 143
        finally:
            stop_process(proc)
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
