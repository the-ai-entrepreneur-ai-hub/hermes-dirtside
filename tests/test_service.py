"""User-service rendering and isolated installation, never real manager calls."""
import argparse
import os
import platform
import plistlib
import shlex
import subprocess

import pytest

from dirtside import cli


def args(*options):
    parser = argparse.ArgumentParser()
    cli.setup_parser(parser)
    return parser.parse_args(["install-service", *options])


def test_service_rendering_for_both_platforms(tmp_path):
    home, state = tmp_path / "user space", tmp_path / "profile%space"
    executable = str(tmp_path / 'bin with "quotes"' / "hermes")
    path, text, log, tool, load, unload = cli.service_spec("Darwin", executable, home, state)
    unit = plistlib.loads(text.encode())
    assert path == home / "Library/LaunchAgents/ai.hermes.dirtside.plist"
    assert unit["ProgramArguments"] == [executable, "dirtside", "serve"]
    assert unit["KeepAlive"] == {"SuccessfulExit": False} and unit["RunAtLoad"] is True
    assert unit["EnvironmentVariables"]["HOME"] == str(home)
    assert unit["EnvironmentVariables"]["HERMES_HOME"] == str(state)
    assert unit["StandardOutPath"] == unit["StandardErrorPath"] == str(log)
    assert tool == "launchctl" and load == [["bootstrap", f"gui/{os.getuid()}", str(path)]]
    assert unload == ["bootout", f"gui/{os.getuid()}", str(path)]
    path, text, log, tool, load, unload = cli.service_spec("Linux", executable, home, state)
    assert path == home / ".config/systemd/user/hermes-dirtside.service"
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert shlex.split(fields["ExecStart"]) == [executable, "dirtside", "serve"]
    assert fields["Restart"] == "on-failure" and fields["UMask"] == "0077"
    assert "HERMES_HOME=" + str(state).replace("%", "%%") in shlex.split(fields["Environment"])
    assert fields["StandardOutput"] == fields["StandardError"] == "append:" + str(log).replace("%", "%%")
    assert tool == "systemctl" and load == [["--user", "daemon-reload"],
                                          ["--user", "enable", "--now", path.name]]
    assert unload == ["--user", "disable", "--now", path.name]


def isolate(tmp_path, monkeypatch, manager=True, system=None):
    home, state = tmp_path / "user", tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(state))
    if system is not None:
        monkeypatch.setattr(cli.platform, "system", lambda: system)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/fake/" + name if manager or name == "hermes" else None)
    calls = []
    def run(command, **kwargs):
        assert command[0] in {"/fake/launchctl", "/fake/systemctl"}
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(cli.subprocess, "run", run)
    return home, state, calls


def test_install_dry_run_writes_nothing_and_never_loads(tmp_path, monkeypatch, capsys):
    home, state, calls = isolate(tmp_path, monkeypatch)
    before = set(tmp_path.rglob("*"))
    assert cli.handle(args("--dry-run")) is None
    output = capsys.readouterr().out
    assert "dirtside" in output and str(state) in output
    assert set(tmp_path.rglob("*")) == before and calls == []
    assert cli.handle(args("--remove", "--dry-run")) is None
    assert set(tmp_path.rglob("*")) == before and not list(home.rglob("*.plist"))


@pytest.mark.parametrize("manager", [False, True])
@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_install_and_remove_are_private_and_idempotent(tmp_path, monkeypatch, manager, system):
    home, state, calls = isolate(tmp_path, monkeypatch, manager, system)
    path, unit, log, _, _, _ = cli.service_spec(platform.system(), "/fake/hermes", home, state)
    assert cli.handle(args()) is None
    assert path.read_text() == unit
    assert path.stat().st_mode & 0o777 == log.stat().st_mode & 0o777 == 0o600
    assert log.parent.stat().st_mode & 0o777 == 0o700
    initial, modified = list(calls), path.stat().st_mtime_ns
    assert cli.handle(args()) is None
    mutations = [c for c in calls if not (c[1] == "print" or "--quiet" in c)]
    assert mutations == initial and path.stat().st_mtime_ns == modified
    assert bool(calls) is manager
    assert cli.handle(args("--remove")) is None and not path.exists()
    after = list(calls)
    assert cli.handle(args("--remove")) is None and calls == after


def test_service_manager_failure_returns_failure_without_private_output(tmp_path, monkeypatch, capsys):
    isolate(tmp_path, monkeypatch)
    def fail(command, **_):
        raise subprocess.CalledProcessError(1, command, stderr="private manager diagnostics")
    monkeypatch.setattr(cli.subprocess, "run", fail)
    assert cli.handle(args()) == 1
    output = capsys.readouterr().out
    assert "Service installation failed" in output and "private manager diagnostics" not in output


def test_unchanged_unit_retries_an_inactive_service(tmp_path, monkeypatch):
    home, state, calls = isolate(tmp_path, monkeypatch, manager=False)
    assert cli.handle(args()) is None and calls == []
    path, _, _, _, loads, _ = cli.service_spec(platform.system(), "/fake/hermes", home, state)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/fake/" + name)
    def inactive(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, 3 if command[1] == "print" or "--quiet" in command else 0)
    monkeypatch.setattr(cli.subprocess, "run", inactive)
    assert cli.handle(args()) is None and path.exists()
    assert [command[1:] for command in calls][-len(loads):] == loads


def test_service_log_symlink_is_not_followed(tmp_path, monkeypatch):
    home, state, calls = isolate(tmp_path, monkeypatch)
    path, _, log, _, _, _ = cli.service_spec(platform.system(), "/fake/hermes", home, state)
    log.parent.mkdir(parents=True)
    victim = tmp_path / "keep.txt"
    victim.write_text("keep")
    log.symlink_to(victim)
    assert cli.handle(args()) == 1
    assert victim.read_text() == "keep" and not path.exists() and not calls


def test_systemd_rejects_injected_lines(tmp_path):
    with pytest.raises(ValueError, match="line breaks"):
        cli.service_spec("Linux", "/bin/hermes\nExecStart=/bad", tmp_path, tmp_path)
    with pytest.raises(ValueError, match="macOS or Linux"):
        cli.service_spec("unsupported", "/bin/hermes", tmp_path, tmp_path)
