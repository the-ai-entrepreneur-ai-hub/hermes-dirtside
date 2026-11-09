"""Plugin-owned cwd and snapshot lifetimes through real core dispatch."""
import ast
import shlex
from contextlib import ExitStack
from pathlib import Path

from core_rig import Core, install
from gateway.session_context import clear_session_vars, set_session_vars
from tools.terminal_tool import get_session_cwd, record_session_cwd

from dirtside.provider import DirtsideProvider
from test_environment import device_setup
from test_target_state_conformance import choose, target_core as target_core


def test_no_terminal_internals():
    root = Path(__file__).resolve().parents[1] / "dirtside"
    imports = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            imports.extend((str(path.relative_to(root)), name) for name in modules
                           if name == "tools.terminal_tool" or name.startswith("tools.terminal_tool."))
    assert imports == []


def test_execution_middleware_matches_manifest():
    from ruamel.yaml import YAML
    from hermes_cli.plugin_validate import _run_capability_probe
    root = Path(__file__).resolve().parents[1]
    manifest = YAML(typ="safe").load(root / "plugin.yaml")
    recorded, error = _run_capability_probe(root, manifest)
    assert recorded is not None, error
    assert recorded["middleware"] == manifest.get("provides_middleware") == ["tool_execution"]

def test_creation_and_selection_never_call_core_cwd_helpers(tmp_path, monkeypatch):
    import tools.terminal_tool as terminal
    relay, device, fake = device_setup(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("plugin touched the private terminal cwd table")
    monkeypatch.setattr(terminal, "get_session_cwd", forbidden)
    monkeypatch.setattr(terminal, "record_session_cwd", forbidden)
    tokens = set_session_vars(session_key="no-core-table")
    env = None
    try:
        env = DirtsideProvider(relay.registry, relay).create_environment(cwd=str(tmp_path), timeout=120)
        with fake:
            for target in ("server", device.id, "server"):
                relay.registry.set_target("no-core-table", target)
                assert env.execute("printf isolated")["output"] == "isolated"
    finally:
        if env:
            env.cleanup()
        clear_session_vars(tokens)


def test_history_comes_from_live_delegate_not_mutable_core_table(tmp_path):
    relay, device, fake = device_setup(tmp_path)
    tokens = set_session_vars(session_key="poisoned-record")
    provider = DirtsideProvider(relay.registry, relay)
    env = provider.create_environment(cwd=str(tmp_path), timeout=120, task_id="different-task")
    project = tmp_path / "real server project"
    project.mkdir()
    poison = str(tmp_path / "not-a-target-directory")
    try:
        assert env.execute("cd " + shlex.quote(str(project)))["returncode"] == 0
        record_session_cwd("poisoned-record", poison)
        with fake:
            relay.registry.set_target("poisoned-record", device.id)
            assert env.execute("printf device")["output"] == "device"
            relay.registry.set_target("poisoned-record", "server")
            assert env.execute("pwd")["output"].strip() == str(project)
        assert provider._states["poisoned-record"]["cwds"][("poisoned-record", "server")] == str(project)
        assert get_session_cwd("poisoned-record") == poison
    finally:
        env.cleanup()
        clear_session_vars(tokens)


def test_direct_cwd_argument_remains_explicit(tmp_path):
    relay, _, _ = device_setup(tmp_path)
    tokens = set_session_vars(session_key="direct-execute")
    env = DirtsideProvider(relay.registry, relay).create_environment(cwd=str(tmp_path), timeout=120)
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    try:
        result = env.execute("pwd", cwd=str(explicit))
        assert result["returncode"] == 0 and result["output"].strip() == str(explicit)
        assert env.cwd == str(explicit)
    finally:
        env.cleanup()
        clear_session_vars(tokens)


def command(core, text, **kwargs):
    return core.call("terminal", session="mismatched-conversation", task_id="unrelated-worker-task",
                     args={"command": text, **kwargs})


def test_gateway_target_roundtrips(target_core):
    core, roots = target_core
    homes = {"server": Path(core.env["HOME"]), **roots}
    projects = {name: home / "review-project" for name, home in homes.items()}
    for name, project in projects.items():
        project.mkdir()
        choose(core, name, session="mismatched-conversation")
        result = command(core, f"export REVIEW_SIDE={name}; cd " + shlex.quote(str(project)))
        assert result["exit_code"] == 0, result
    for _ in range(3):
        for name, project in projects.items():
            choose(core, name, session="mismatched-conversation")
            result = command(core, 'pwd; printf %s "$REVIEW_SIDE"')
            assert result["exit_code"] == 0 and result["output"] == str(project) + "\n" + name, result
            transient = project.parent
            assert command(core, "pwd", workdir=str(transient))["output"] == str(transient)
            assert command(core, "pwd")["output"] == str(project)


def test_switch_after_idle_cleanup(target_core):
    core, roots = target_core
    project = roots["device-a"] / "reaped-review-project"
    project.mkdir()
    choose(core, "device-a", session="mismatched-conversation")
    assert command(core, "export REVIEW_REAP=old; cd " + shlex.quote(str(project)))["exit_code"] == 0
    assert core.call("reap", session="mismatched-conversation")["identity"] is None
    choose(core, "server", session="mismatched-conversation")
    assert command(core, "pwd")["output"] == core.env["HOME"]
    choose(core, "device-a", session="mismatched-conversation")
    result = command(core, 'pwd; printf %s "${REVIEW_REAP-unset}"')
    assert result["exit_code"] == 0 and result["output"] == str(project) + "\nunset", result


def test_server_environment_control(tmp_path):
    names = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
    with ExitStack() as stack:
        results = []
        for backend in ("dirtside", "local"):
            home = tmp_path / backend
            env = install(home, backend=backend)
            env.update({name: "fake-provider-key-not-for-child" for name in names})
            core = stack.enter_context(Core(home, env=env))
            result = core.terminal("env")
            assert result["exit_code"] == 0
            child_names = {line.partition("=")[0] for line in result["output"].splitlines()}
            assert "fake-provider-key-not-for-child" not in result["output"]
            results.append(child_names.intersection(names))
        assert results == [set(), set()]
