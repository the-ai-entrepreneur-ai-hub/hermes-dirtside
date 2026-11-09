"""Device-owned environment policy at the real process boundary."""
import json
import os
import uuid
from dataclasses import replace

import pytest
from hermes_constants import reset_hermes_home_override, set_hermes_home_override

from dirtside.agent.config import DeviceConfig, default_policy, parse_policy, policy_data
from dirtside.agent.executor import run
from dirtside.cli import handle
from dirtside.protocol import WireExec
from test_agent import config
from test_cli import parser

SECRET_NAMES = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "HERMES_TEST_SECRET")
BASH_NAMES = {"PWD", "SHLVL", "_"}


@pytest.fixture
def planted(tmp_path, monkeypatch):
    for name in list(os.environ):
        monkeypatch.delenv(name)
    allowed = dict(PATH=os.defpath, HOME=str(tmp_path), USER="device-owner", LANG="C",
                   LC_ALL="C", LC_DIRTSIDE_TEST="owner-locale", TERM="dumb", TMPDIR=str(tmp_path))
    secrets = {name: "fake-" + uuid.uuid4().hex for name in (*SECRET_NAMES, "DIRTSIDE_SECRET_" + uuid.uuid4().hex)}
    for name, value in (allowed | secrets).items():
        monkeypatch.setenv(name, value)
    for name in (".profile", ".bash_profile", ".bash_login", ".bashrc"):
        (tmp_path / name).write_text("")
    return allowed, secrets


def child(root, *, policy=None, login=False, stdin=None, script="env -0"):
    parts = []
    req = WireExec("r_" + "ad" * 12, script, script, login, 30, stdin, str(root))
    outcome, tail = run(req, policy or default_policy(), lambda _, data: parts.append(data) or True)
    if tail:
        parts.append(tail.data)
    assert outcome.exit_code == 0, outcome
    return b"".join(parts)


def variables(output):
    return dict(part.decode().split("=", 1) for part in output.split(b"\0") if part)


@pytest.mark.parametrize("stdin", [None, "unused input"])
def test_executor_exact_environment(tmp_path, planted, stdin):
    allowed, secrets = planted
    before = dict(os.environ)
    output = child(tmp_path, stdin=stdin)
    actual = variables(output)
    assert set(actual) == set(allowed) | BASH_NAMES
    assert all(actual[name] == value for name, value in allowed.items())
    assert all(name not in actual and value.encode() not in output for name, value in secrets.items())
    assert dict(os.environ) == before


def test_login_environment(tmp_path, planted):
    allowed, secrets = planted
    output = child(tmp_path, login=True, stdin="unused")
    actual = variables(output)
    assert all(name in actual for name in allowed)
    assert all(name not in actual and value.encode() not in output for name, value in secrets.items())
    assert actual["HOME"] == allowed["HOME"] and actual["USER"] == allowed["USER"]


def test_declared_passthrough(tmp_path, planted, monkeypatch):
    allowed, secrets = planted
    monkeypatch.setenv("OWNER_SERVICE_TOKEN", "fake-declared-only")
    policy = parse_policy(policy_data(default_policy()) | {
        "env_passthrough": ["OWNER_SERVICE_TOKEN", "DECLARED_BUT_UNSET"]})
    output = child(tmp_path, policy=policy)
    actual = variables(output)
    assert set(actual) == set(allowed) | BASH_NAMES | {"OWNER_SERVICE_TOKEN"}
    assert actual["OWNER_SERVICE_TOKEN"] == "fake-declared-only"
    assert all(name not in actual and value.encode() not in output for name, value in secrets.items())


def test_policy_files(tmp_path):
    path = tmp_path / "device.json"
    cfg = config()
    cfg.save(path)
    old = json.loads(path.read_text())
    old["policy"].pop("env_passthrough", None)
    assert len(old["policy"]) == 4
    path.write_text(json.dumps(old))
    loaded = DeviceConfig.load(path)
    assert loaded.policy.env_passthrough == ()
    loaded.save(path)
    assert json.loads(path.read_text())["policy"]["env_passthrough"] == []
    policy = parse_policy(old["policy"] | {"env_passthrough": ["_x", "A" * 128]})
    updated = replace(loaded, policy=policy)
    updated.save(path)
    assert DeviceConfig.load(path) == updated
    assert policy_data(policy)["env_passthrough"] == ["_x", "A" * 128]


@pytest.mark.parametrize("names", [
    None, "PATH", 1, {}, [1], [True], ["bad-name"], ["1BAD"], [""], ["x=y"],
    ["x\n"], ["A" * 129], ["é"], ["A", "A"], ["N" + str(n) for n in range(65)],
])
def test_bad_passthrough_refused(names):
    data = policy_data(default_policy()) | {"env_passthrough": names}
    with pytest.raises(ValueError, match="env_passthrough"):
        parse_policy(data)


def test_passthrough_limit_and_unknown_keys():
    data = policy_data(default_policy())
    policy = parse_policy(data | {"env_passthrough": ["N" + str(n) for n in range(64)]})
    assert len(policy.env_passthrough) == 64
    with pytest.raises(ValueError, match="policy"):
        parse_policy(data | {"gateway_env": ["SECRET"]})


def test_policy_cli(tmp_path, monkeypatch, capsys):
    scope = set_hermes_home_override(tmp_path)
    try:
        config().save()
        monkeypatch.setenv("OWNER_SERVICE_TOKEN", "fake-never-print-this-value")
        def invoke(*args):
            result = parser().parse_args(["dirtside", "policy", *args])
            assert handle(result) is None
            output = capsys.readouterr().out
            assert "fake-never-print-this-value" not in output
            return output
        assert "none" in invoke().lower()
        assert "OWNER_SERVICE_TOKEN" in invoke("--env-passthrough", "OWNER_SERVICE_TOKEN", "UNSET_NAME")
        assert DeviceConfig.load().policy.env_passthrough == ("OWNER_SERVICE_TOKEN", "UNSET_NAME")
        assert "OWNER_SERVICE_TOKEN" in invoke()
        started = []
        monkeypatch.setattr("dirtside.cli.serve", lambda cfg: started.append(cfg))
        assert handle(parser().parse_args(["dirtside", "serve"])) is None
        output = capsys.readouterr().out
        assert "OWNER_SERVICE_TOKEN" in output and "fake-never-print-this-value" not in output
        assert started[0].policy.env_passthrough == ("OWNER_SERVICE_TOKEN", "UNSET_NAME")
        assert "none" in invoke("--clear-env-passthrough").lower()
        assert DeviceConfig.load().policy.env_passthrough == ()
    finally:
        reset_hermes_home_override(scope)


def test_commands_keep_device_basics(tmp_path, planted):
    allowed, _ = planted
    output = child(tmp_path, script="command -v sh; pwd; printf '%s\\n%s\\n' \"$HOME\" \"$USER\"").decode()
    assert output.splitlines() == ["/bin/sh", str(tmp_path), allowed["HOME"], allowed["USER"]]
