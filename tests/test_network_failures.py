"""Loss, output retry and restart conformance over the production HTTP routes."""
import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from contextlib import ExitStack

import pytest
from fastapi.responses import JSONResponse
from network_support import listening, mounted, subprocess_agent, until

from dirtside.environment import DirtsideEnvironment
from dirtside.model import LOST_GRACE_S, OFFLINE_AFTER_S, PART_MAX, Outcome, RequestState
from dirtside.relay import Relay
from test_executor import alive, await_file
from test_network import group, revoke, setup_agent, stop_group
from test_registry import request
from client_support import client_relay


@pytest.fixture(params=["in-process", "client"])
def transport(request):
    with ExitStack() as stack:
        def connect(relay, url):
            return stack.enter_context(client_relay(relay, url)) if request.param == "client" else relay
        yield connect


@pytest.mark.slow
def test_subprocess_sigkill_loses_at_real_deadline_with_partial_output(tmp_path, transport):
    with mounted(tmp_path) as (app, reg, relay, _), listening(app) as url:
        device, cfg = setup_agent(reg, tmp_path, url)
        with subprocess_agent(cfg, tmp_path / "install") as proc:
            until(lambda: relay.is_online(device.id))
            remote = DirtsideEnvironment(transport(relay, url), device, "chat", "default", "~", 120)
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(remote.execute, "echo $$ > lost.pid; printf retained; sleep 120")
                pid = int(await_file(tmp_path / "lost.pid"))
                pids = group(pid)
                try:
                    until(lambda: any(b"retained" in relay.tail(rid) for rid in list(relay.handles)))
                    start = time.monotonic()
                    proc.kill()
                    proc.wait(timeout=2)
                    result = future.result(timeout=OFFLINE_AFTER_S + LOST_GRACE_S + 2)
                    elapsed = time.monotonic() - start
                    assert OFFLINE_AFTER_S + LOST_GRACE_S - 1 < elapsed < OFFLINE_AFTER_S + LOST_GRACE_S + 1
                    assert result["returncode"] == 255 and "retained" in result["output"]
                    assert reg.recent(1)[0].state is RequestState.LOST
                finally:
                    relay.revoke(device.id)
                    stop_group(pid)
                    until(lambda: not any(alive(p) for p in pids))


def test_subprocess_retries_first_accepted_chunk_without_doubled_bytes(tmp_path, transport):
    with mounted(tmp_path) as (app, reg, relay, _):
        posts = []

        @app.middleware("http")
        async def fail_once(request, call_next):
            is_chunk = request.url.path.endswith("/device/chunk")
            if is_chunk:
                posts.append((await request.json())["body"])
            response = await call_next(request)
            return JSONResponse({}, status_code=503) if is_chunk and len(posts) == 1 else response

        with listening(app) as url:
            device, cfg = setup_agent(reg, tmp_path, url)
            with subprocess_agent(cfg, tmp_path / "install") as proc:
                until(lambda: relay.is_online(device.id))
                remote = DirtsideEnvironment(transport(relay, url), device, "chat", "default", "~", 120)
                repeats = (3 * PART_MAX + 5) // 6
                payload = "abcdef" * repeats
                command = f"{shlex.quote(sys.executable)} -c 'print(\"abcdef\" * {repeats}, end=\"\")'"
                result = remote.execute(command)
                assert result["returncode"] == 0 and result["output"] == payload
                assert len(posts) >= 4 and posts[0] == posts[1] and posts[0]["seq"] == 0
                assert [p["seq"] for p in posts] == [0] + list(range(len(posts) - 1))
                revoke(url, device.name)
                assert proc.wait(timeout=5) == 0


def test_upload_retries_cannot_extend_device_command_timeout(tmp_path, transport):
    with mounted(tmp_path) as (app, reg, relay, _):
        @app.middleware("http")
        async def unavailable_chunks(request, call_next):
            response = await call_next(request)
            return JSONResponse({}, status_code=503) if request.url.path.endswith("/device/chunk") else response

        with listening(app) as url:
            device, cfg = setup_agent(reg, tmp_path, url)
            with subprocess_agent(cfg, tmp_path / "install") as proc:
                until(lambda: relay.is_online(device.id))
                req = request(device, command="echo $$ > deadline.pid; printf retained; sleep 60")
                handle = transport(relay, url).connection().submit(replace(req, timeout_s=1))
                pid = int(await_file(tmp_path / "deadline.pid"))
                pids = group(pid)
                try:
                    assert handle.wait(timeout=5) == 124
                    assert handle.stdout.read() == b"retained" and not any(alive(p) for p in pids)
                finally:
                    revoke(url, device.name)
                    assert proc.wait(timeout=5) == 0
                    stop_group(pid)


class RestartedApp:
    def __init__(self, app):
        self.app = self.original = app
        self.active = 0
        self.drained, self.unavailable = threading.Event(), threading.Event()
        self.drained.set()

    async def __call__(self, scope, receive, send):
        app = self.app
        if app is None:
            self.unavailable.set()
            return await JSONResponse({}, status_code=503)(scope, receive, send)
        old = app is self.original
        if old:
            self.active += 1
            self.drained.clear()
        try:
            await app(scope, receive, send)
        finally:
            if old:
                self.active -= 1
                if self.active == 0:
                    self.drained.set()


def test_subprocess_gateway_restart_rejects_old_work_and_reuses_pairing(tmp_path, transport):
    with mounted(tmp_path) as (old_app, reg, old_relay, old_module):
        old_routes = old_module.auth.routes
        old_key = bytes(old_module.relay_key)
        old_relay._routes_enabled = lambda: old_routes.enabled
        switch = RestartedApp(old_app)
        with listening(switch) as url:
            device, cfg = setup_agent(reg, tmp_path, url)
            with subprocess_agent(cfg, tmp_path / "install") as proc:
                until(lambda: old_relay.is_online(device.id))
                handle = transport(old_relay, url).connection().submit(request(
                    device, command="echo $$ > restart.pid; while :; do printf tick; sleep 0.1; done"))
                pid = int(await_file(tmp_path / "restart.pid"))
                try:
                    until(lambda: old_relay.tail(handle.req.id))
                    switch.app = None
                    reg.mark_stale_lost(int(time.time()))
                    old_routes.dispose()
                    with old_relay._condition:
                        old_relay._condition.notify_all()
                    old_relay.close(handle.req.id, Outcome(RequestState.LOST, 255, 0, False, "gateway restarted"))
                    assert switch.drained.wait(2), "old requests did not leave before replacement"
                    assert switch.unavailable.wait(5), "agent did not see the restart interval"
                    assert handle.wait(timeout=1) == 255
                    with mounted(tmp_path, relay=Relay(reg)) as (new_app, _, new_relay, new_module):
                        rejected, polls = [], []

                        @new_app.middleware("http")
                        async def observe(request, call_next):
                            response = await call_next(request)
                            if request.url.path.endswith("/device/chunk") and response.status_code == 410:
                                rejected.append(True)
                            if request.url.path.endswith("/device/poll"):
                                polls.append(response.status_code)
                            return response

                        assert bytes(new_module.relay_key) == old_key
                        switch.app = new_app
                        until(lambda: rejected, timeout=5)
                        until(lambda: not alive(pid), timeout=5)
                        until(lambda: new_relay.is_online(device.id), timeout=30)
                        assert reg.credential_for(cfg.token, int(time.time())) == device and proc.poll() is None
                        fresh = transport(new_relay, url).connection().submit(request(device, n=2, command="printf reconnected"))
                        assert fresh.wait(timeout=30) == 0 and fresh.stdout.read() == b"reconnected"
                        assert 200 in polls
                        revoke(url, device.name)
                        assert proc.wait(timeout=5) == 0
                finally:
                    old_relay.revoke(device.id)
                    stop_group(pid)
