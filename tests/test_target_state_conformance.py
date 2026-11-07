"""Real-core target switches must preserve only the selected target's shell state."""
import shlex
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pytest
from core_rig import Core, Rig, install

from dirtside.provider import DirtsideProvider


def choose(core, name, session="chat"):
    reply = core.call("slash", session=session, raw_args="use " + name)
    assert name in reply and "from the next command" in reply, reply


def completed(core, command, *, output=None, cwd=None, **kwargs):
    result = core.terminal(command, **kwargs)
    assert result["exit_code"] == 0, result
    if output is not None:
        assert result["output"] == str(output), result
    if cwd is not None:
        assert core.call("state", session=kwargs.get("session", "chat"))["cwd"] == str(cwd), result
        if "cwd" in result:
            assert result["cwd"] == str(cwd), result
    return result


@contextmanager
def unavailable(directory):
    # Disjoint device filesystems: A's directory is absent while B or server runs.
    parked = directory.with_name(directory.name + "-parked")
    directory.rename(parked)
    try:
        assert not directory.exists()
        yield
    finally:
        parked.rename(directory)


@pytest.fixture(params=["in-process", "client"])
def target_core(tmp_path, request):
    home = tmp_path / "gateway"
    env = install(home)
    env.pop("X", None)
    roots = {name: (tmp_path / name).resolve() for name in ("device-a", "device-b")}
    with ExitStack() as stack:
        owner = stack.enter_context(Core(home, env=env))
        for name, root in roots.items():
            root.mkdir()
            owner.call("fake_device", name=name, root=str(root))
            choose(owner, name, session="setup-" + name)
            completed(owner, "printf ready", output="ready", cwd=root, session="setup-" + name)
        core = stack.enter_context(Core(owner.home, env=owner.env, worker=True)) if request.param == "client" else owner
        assert core.call("info")["owner_pid"] == (None if request.param == "client" else owner.proc.pid)
        yield core, roots
    assert owner.proc.returncode == 0
    assert core.proc.returncode == 0


@pytest.mark.parametrize("via_server", [False, True], ids=["device-to-device", "through-server"])
def test_target_switch_restores_cwd_and_exports(target_core, via_server):
    core, roots = target_core
    a, b = roots["device-a"], roots["device-b"]
    project_a, project_b = a / "project only on A", b / "project only on B"
    project_a.mkdir()
    project_b.mkdir()
    server_home = Path(core.env["HOME"]).resolve()
    server_project = server_home / "server project"
    server_project.mkdir()
    choose(core, "device-a")
    completed(core, "pwd", output=a, cwd=a)
    cached = core.call("state", session="chat")["identity"]
    completed(core, "export X=1; cd " + shlex.quote(str(project_a)), cwd=project_a)
    with unavailable(project_a):
        if via_server:
            choose(core, "server")
            completed(core, "pwd", output=server_home, cwd=server_home)
            completed(core, "printf '%s' \"${X-unset}\"", output="unset")
            completed(core, "export X=server; cd " + shlex.quote(str(server_project)), cwd=server_project)
        choose(core, "device-b")
        completed(core, "pwd", output=b, cwd=b)
        completed(core, "printf '%s' \"${X-unset}\"", output="unset")
        completed(core, "export X=2; cd " + shlex.quote(str(project_b)), cwd=project_b)
        completed(core, "printf command-on-b", output="command-on-b")
    choose(core, "device-a")
    completed(core, "pwd", output=project_a, cwd=project_a)
    completed(core, "printf '%s' \"$X\"", output="1")
    assert core.call("state", session="chat")["identity"] == cached
    choose(core, "device-b")
    completed(core, "pwd", output=project_b, cwd=project_b)
    completed(core, "printf '%s' \"$X\"", output="2")
    if via_server:
        choose(core, "server")
        completed(core, "pwd", output=server_project, cwd=server_project)
        completed(core, "printf '%s' \"$X\"", output="server")
    choose(core, "device-a", session="other")
    completed(core, "pwd", output=a, cwd=a, session="other")
    completed(core, "printf '%s' \"${X-unset}\"", output="unset", session="other")


def test_deleted_target_cwd_keeps_its_failure_on_return(target_core):
    core, roots = target_core
    project = roots["device-a"] / "deleted"
    project.mkdir()
    choose(core, "device-a")
    completed(core, "cd " + shlex.quote(str(project)), cwd=project)
    project.rmdir()
    first = core.terminal("printf must-not-run")
    assert first["exit_code"] == 126 and "No such file or directory" in first["output"], first
    assert "must-not-run" not in first["output"]
    choose(core, "server")
    completed(core, "pwd", output=Path(core.env["HOME"]).resolve())
    choose(core, "device-a")
    again = core.terminal("printf must-not-run")
    assert again == first


def test_server_transient_workdir_matches_core_local_after_switch(target_core, tmp_path):
    core, roots = target_core
    persistent, transient = tmp_path / "persistent", tmp_path / "transient"
    persistent.mkdir()
    transient.mkdir()
    choose(core, "server")
    with Core(tmp_path / "local", backend="local", user_home=Path(core.env["HOME"])) as local:
        for current in (core, local):
            completed(current, "cd " + shlex.quote(str(persistent)))
            completed(current, "pwd", output=transient, workdir=str(transient))
        choose(core, "device-a")
        completed(core, "pwd", output=roots["device-a"])
        choose(core, "server")
        actual = completed(core, "pwd", output=persistent)
        expected = completed(local, "pwd", output=persistent)
        assert {k: actual[k] for k in ("output", "exit_code", "error")} == {
            k: expected[k] for k in ("output", "exit_code", "error")}


def test_file_first_switch_uses_selected_target_directory(target_core):
    core, roots = target_core
    project = roots["device-a"] / "only A"
    project.mkdir()
    (project / "marker.txt").write_text("device-a\n")
    (roots["device-b"] / "marker.txt").write_text("device-b\n")
    choose(core, "device-a")
    completed(core, "cd " + shlex.quote(str(project)))
    with unavailable(project):
        choose(core, "device-b")
        result = core.call("file", session="chat", tool="read_file", args={"path": "marker.txt"})
        assert not result.get("error") and "device-b" in str(result), result
        assert "device-a" not in str(result), result
        completed(core, "pwd", output=roots["device-b"], cwd=roots["device-b"])


@pytest.mark.parametrize("file_first", [False, True], ids=["terminal-first", "file-first"])
def test_reaped_device_retains_cwd(target_core, file_first):
    core, roots = target_core
    project = roots["device-a"] / "retained after reap"
    project.mkdir()
    (project / "marker.txt").write_text("retained-after-reap\n")
    choose(core, "device-a")
    completed(core, "cd " + shlex.quote(str(project)), cwd=project)
    assert core.call("reap", session="chat")["identity"] is None
    if file_first:
        result = core.call("file", session="chat", tool="read_file", args={"path": "marker.txt"})
        assert not result.get("error") and "retained-after-reap" in str(result), result
    completed(core, "pwd", output=project, cwd=project)


@pytest.mark.parametrize("visited_server", [False, True], ids=["server-first-use", "server-return"])
def test_server_switch_during_reaping_uses_its_own_cwd(target_core, visited_server):
    core, roots = target_core
    server = Path(core.env["HOME"]).resolve()
    if visited_server:
        server = server / "saved server directory"
        server.mkdir()
        choose(core, "server")
        completed(core, "cd " + shlex.quote(str(server)), cwd=server)
    (server / "marker.txt").write_text("server-after-reap\n")
    project = roots["device-a"] / "not on server"
    project.mkdir()
    choose(core, "device-a")
    completed(core, "cd " + shlex.quote(str(project)), cwd=project)
    assert core.call("reap", session="chat")["identity"] is None
    with unavailable(project):
        choose(core, "server")
        result = core.call("file", session="chat", tool="read_file", args={"path": "marker.txt"})
        assert not result.get("error") and "server-after-reap" in str(result), result
        completed(core, "pwd", output=server, cwd=server)
    choose(core, "device-a")
    completed(core, "pwd", output=project, cwd=project)


def test_device_switch_during_reaping_preserves_both_cwds(target_core):
    core, roots = target_core
    a, b = (roots[name] / "saved project" for name in ("device-a", "device-b"))
    for name, project in (("device-b", b), ("device-a", a)):
        project.mkdir()
        choose(core, name)
        completed(core, "cd " + shlex.quote(str(project)), cwd=project)
    assert core.call("reap", session="chat")["identity"] is None
    with unavailable(a):
        choose(core, "device-b")
        completed(core, "pwd", output=b, cwd=b)
    choose(core, "device-a")
    completed(core, "pwd", output=a, cwd=a)


@pytest.fixture(params=["in-process", "client"])
def paired_core(tmp_path, request):
    with Rig(tmp_path / "offline-rig") as rig, ExitStack() as stack:
        rig.pair()
        core = stack.enter_context(Core(rig.core.home, env=rig.core.env, worker=True)) if request.param == "client" else rig.core
        assert core.call("info")["owner_pid"] == (None if request.param == "client" else rig.core.proc.pid)
        yield core, rig
    assert core.proc.returncode == rig.core.proc.returncode == 0


def test_offline_first_selection_bootstraps_after_contact(paired_core, tmp_path):
    core, rig = paired_core
    completed(core, "pwd", output=core.env["HOME"])
    choose(core, rig.name)
    marker = tmp_path / "must-not-run"
    result = core.terminal("printf forbidden > " + shlex.quote(str(marker)))
    assert result["exit_code"] != 0 and "offline" in str(result).lower(), result
    assert "Nothing was run on the server" in str(result) and not marker.exists()
    rig.start_agent()
    completed(core, "export X=1")
    completed(core, "printf '%s' \"$X\"", output="1")
    completed(core, "pwd", output=rig.device_env["HOME"], cwd=rig.device_env["HOME"])


@pytest.mark.parametrize("unavailable_target", ["offline", "revoked"])
def test_unavailable_target_cwd_metadata_keeps_last_directory(paired_core, tmp_path, unavailable_target):
    core, rig = paired_core
    if unavailable_target == "revoked":
        rig.start_agent()
        choose(core, rig.name)
    directory = tmp_path / "last known directory"
    directory.mkdir()
    completed(core, "cd " + shlex.quote(str(directory)), cwd=directory)
    if unavailable_target == "revoked":
        core.call("slash", session="chat", raw_args="revoke " + rig.name)
    else:
        choose(core, rig.name)
    assert core.call("state", session="chat")["cwd"] == str(directory)
    result = core.terminal("printf must-not-run")
    assert result["exit_code"] != 0 and "must-not-run" not in result["output"], result


def test_provider_transition_history_is_lru_bounded():
    provider = DirtsideProvider(None, None)
    states = [provider._state(str(index), "~") for index in range(1024)]
    assert len(provider._states) == 1024
    assert provider._state("0", "/must-not-replace") is states[0]
    provider._state("1024", "~")
    assert len(provider._states) == 1024
    assert "1" not in provider._states and provider._states["0"] is states[0]
    assert states[0]["cwds"][("0", "server")] == "~"
