"""Real subprocess agent signals, bounded parallelism and cancellation."""
import os
import signal
import time
from dataclasses import replace

import httpx
import psutil
import pytest
from nacl.signing import SigningKey
from network_support import DESKTOP_TOKEN, listening, mounted, subprocess_agent, until

from dirtside.agent.config import DeviceConfig, default_policy
from test_executor import alive, await_file
from test_registry import paired, request


def setup_agent(reg, root, url, parallel=4):
    device, token, key = paired(reg, root, now=int(time.time()))
    cfg = DeviceConfig(url, device.id, token, key, SigningKey(reg.relay_seed).verify_key,
                       device.name, replace(default_policy(), max_parallel=parallel))
    return device, cfg


def group(pid):
    return [pid] + [child.pid for child in psutil.Process(pid).children(recursive=True)]


def revoke(url, name):
    with httpx.Client(headers={"Authorization": f"Bearer {DESKTOP_TOKEN}"}) as client:
        assert client.post(url + f"/api/plugins/dirtside/devices/{name}/revoke").status_code == 200


def stop_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_subprocess_signal_stops_entire_group(tmp_path, sig):
    with mounted(tmp_path) as (app, reg, relay, _), listening(app) as url:
        device, cfg = setup_agent(reg, tmp_path, url)
        with subprocess_agent(cfg, tmp_path / "install") as proc:
            until(lambda: relay.is_online(device.id))
            handle = relay.submit(request(device, command="echo $$ > signal.pid; printf partial; sleep 60"))
            pid = int(await_file(tmp_path / "signal.pid"))
            try:
                until(lambda: relay.tail(handle.req.id) == b"partial")
                pids = group(pid)
                assert len(pids) >= 2
                start = time.monotonic()
                proc.send_signal(sig)
                assert proc.wait(timeout=5) == 0
                until(lambda: not any(alive(p) for p in pids))
                assert time.monotonic() - start < 5
            finally:
                handle.kill()
                stop_group(pid)
            assert handle.stdout.read() == b"partial"
            relay.revoke(device.id)


def test_parallel_limit_keeps_poll_cancellation_live(tmp_path):
    with mounted(tmp_path) as (app, reg, relay, _), listening(app) as url:
        device, cfg = setup_agent(reg, tmp_path, url, parallel=2)
        with subprocess_agent(cfg, tmp_path / "install") as proc:
            until(lambda: relay.is_online(device.id))
            handles = [relay.submit(request(device, n=n, command=f"echo $$ > parallel-{n}.pid; sleep 60"))
                       for n in (1, 2, 3)]
            first = int(await_file(tmp_path / "parallel-1.pid"))
            second = int(await_file(tmp_path / "parallel-2.pid"))
            try:
                until(lambda: len(group(second)) >= 2)
                first_group, second_group = group(first), group(second)
                time.sleep(0.3)
                assert not (tmp_path / "parallel-3.pid").exists()
                start = time.monotonic()
                handles[0].kill()
                assert handles[0].wait(0) == 130
                third = int(await_file(tmp_path / "parallel-3.pid"))
                until(lambda: not any(alive(p) for p in first_group), timeout=5)
                assert time.monotonic() - start < 5 and alive(second) and alive(third)
                third_group = group(third)
                revoke(url, device.name)
                assert all(h.wait(0) == 130 for h in handles)
                assert proc.wait(timeout=5) == 0
                assert not any(alive(p) for p in second_group + third_group)
            finally:
                relay.revoke(device.id)
                for path in tmp_path.glob("parallel-*.pid"):
                    stop_group(int(path.read_text()))
