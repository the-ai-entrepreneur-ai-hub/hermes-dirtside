"""Normal core terminal and file entry points through a paired subprocess device."""
import re
import shlex
import time
from pathlib import Path

import pytest
from core_rig import Core, Rig, until

pytestmark = pytest.mark.slow


def semantic(result):
    """Core adds cwd display metadata to remote results; compare cwd separately."""
    return {k: result[k] for k in ("output", "exit_code", "error")}


def file(core, tool, **args):
    return core.call("file", tool=tool, args=args, session="chat")


def test_terminal_and_file_entry_points_agree_with_local(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        device_user = Path(rig.device_env["HOME"])
        with Core(tmp_path / "local", backend="local", user_home=device_user) as local:
            remote = rig.core
            commands = ["pwd", "cd /tmp", "pwd", "export X=1", "echo $X", "exit 3"]
            states = []
            for command in commands:
                actual = remote.terminal(command)
                expected = local.terminal(command)
                assert semantic(actual) == semantic(expected), (command, actual, expected)
                states.append(remote.call("state", session="chat"))
                assert states[-1]["cwd"] == local.call("state", session="chat")["cwd"]
                assert remote.call("turn_end", session="chat")["identity"] == states[-1]["identity"]
            assert states[0]["environment"] == "ConversationEnvironment"
            assert states[0]["persistent"] and states[0]["key"] == "session:chat"
            assert len({s["identity"] for s in states}) == 1
            assert remote.terminal("pwd")["output"].strip() == str(Path("/tmp").resolve())
            # Core bounds the foreground view but retains a recovery file with all bytes.
            flood = "head -c 1048576 /dev/zero | tr '\\0' x"
            actual, expected = remote.terminal(flood), local.terminal(flood)
            assert actual["exit_code"] == expected["exit_code"] == 0
            assert actual["output"].replace(actual["full_output_path"], "<recovery>") == expected["output"].replace(
                expected["full_output_path"], "<recovery>")
            assert len(actual["output"]) == len(expected["output"])
            assert actual["output"][:100] == expected["output"][:100] == "x" * 100
            assert actual["output"][-100:] == expected["output"][-100:] == "x" * 100
            assert actual["output_total_chars"] == expected["output_total_chars"]
            recovered = [Path(result["full_output_path"]).read_bytes() for result in (actual, expected)]
            # Core's raw spill includes shell trailers; normalize only their random session ids.
            normalized = [re.sub(br"(__HERMES_(?:PIPE|CWD)_)[a-f0-9]{12}__", br"\1session__", data)
                          for data in recovered]
            trailer = ("\n__HERMES_PIPE_session__0 0__HERMES_PIPE_session__\n\n"
                       f"__HERMES_CWD_session__{Path('/tmp').resolve()}__HERMES_CWD_session__\n").encode()
            assert normalized[0] == normalized[1] == b"x" * 1048576 + trailer
            path = tmp_path / "payload.txt"
            content = "unique-original\n" + "0123456789abcdef\n" * 5882
            assert len(content) >= 100_000
            results = []
            for core in (remote, local):
                assert core.terminal("cd " + shlex.quote(str(tmp_path)))["exit_code"] == 0
                written = file(core, "write_file", path=str(path), content=content)
                assert not written.get("error"), written
                raw = path.read_bytes()
                assert raw == content.encode()
                read = file(core, "read_file", path=str(path), offset=1, limit=10_000)
                patched = file(core, "patch", path=str(path), old_string="unique-original",
                               new_string="unique-patched")
                searched = file(core, "search_files", pattern="unique-patched", path=str(path))
                assert path.read_text() == content.replace("unique-original", "unique-patched")
                results.append((written, read, patched, searched))
                path.unlink()
            # Core cannot establish a host-stat baseline for any remote backend.
            warning = results[0][2].pop("_warning")
            assert "partial view" in warning and "_warning" not in results[1][2]
            assert results[0] == results[1]
            assert remote.call("state", session="chat")["identity"] == states[0]["identity"]
            assert remote.call("reap", session="chat")["identity"] is None


def test_cached_device_offline_fails_closed_then_no_target_is_local(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        core = rig.core
        assert core.terminal("pwd")["exit_code"] == 0
        cached = core.call("state", session="chat")["identity"]
        rig.stop_agent()
        until(lambda: not rig.online(), timeout=48)
        assert core.call("state", session="chat")["identity"] == cached
        marker = tmp_path / "must-not-run"
        started = time.monotonic()
        result = core.terminal("printf forbidden > " + shlex.quote(str(marker)), timeout=10)
        assert "offline" in str(result).lower(), result
        assert "Nothing was run on the server" in str(result)
        assert result["exit_code"] != 0 and not marker.exists()
        assert time.monotonic() - started < 20
        assert core.terminal("pwd", session="unselected")["output"].strip() == core.env["HOME"]
        assert core.call("state", session="unselected")["environment"] == "ConversationEnvironment"
        assert core.terminal("cd /tmp", session="unselected")["exit_code"] == 0
        core.call("turn_end", session="unselected")
        assert core.terminal("pwd", session="unselected")["output"].strip() == str(Path("/tmp").resolve())


def test_file_first_uses_selected_environment(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent().choose()
        path = tmp_path / "first.txt"
        result = file(rig.core, "write_file", path=str(path), content="file-first\n")
        assert not result.get("error"), result
        assert path.read_text() == "file-first\n"
        assert rig.core.call("state", session="chat")["environment"] == "ConversationEnvironment"
