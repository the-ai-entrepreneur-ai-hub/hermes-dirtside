"""Short commands dispatch through core and share long-form storage and authority."""
import sqlite3
from contextlib import closing

import pytest
from core_rig import Rig


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))


def stored(rig):
    with closing(sqlite3.connect(rig.core.info["registry"])) as conn:
        row = conn.execute("SELECT target FROM targets WHERE session_key='chat'").fetchone()
    return row[0] if row else None


def slash(rig, command, raw="", **kwargs):
    return rig.core.call("slash", command=command, raw_args=raw, session="chat", **kwargs)


def test_land_orbit_real_dispatch(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent()
        slash(rig, "dirtside", "use laptop")
        long_device = stored(rig)
        slash(rig, "dirtside", "use server")
        long_server = stored(rig)
        reply = slash(rig, "land", "laptop")
        assert reply.startswith("Landed on laptop") and rig.device_env["HOME"] in reply
        assert stored(rig) == long_device
        result = rig.core.terminal('printf "%s" "$HOME"', timeout=5)
        assert result["output"] == rig.device_env["HOME"]
        assert slash(rig, "orbit") == "Back in orbit. Commands run on the server."
        assert stored(rig) == long_server == "server"
        assert rig.core.terminal('printf "%s" "$HOME"', timeout=5)["output"] == rig.core.env["HOME"]


def test_shortcut_owner_picker_and_usage(tmp_path):
    with Rig(tmp_path / "rig") as rig:
        rig.pair().start_agent()
        sender = dict(platform="telegram", source="telegram", user_id="visitor")
        refusal = slash(rig, "dirtside", "use laptop", **sender)
        assert slash(rig, "land", "laptop", **sender) == refusal
        assert stored(rig) is None
        long = slash(rig, "dirtside", "use", choice="laptop")
        long_target = stored(rig)
        slash(rig, "orbit")
        short = slash(rig, "land", choice="laptop")
        assert short["questions"] == long["questions"] == [
            ["Where should this conversation run commands?", ["laptop", "server"]]]
        assert stored(rig) == long_target
        for command, raw in (("land", "laptop extra"), ("orbit", "extra")):
            assert f"Use /{command}" in slash(rig, command, raw)
            assert stored(rig) == long_target
        cancel = slash(rig, "land", choice=None)
        assert cancel["reply"] == "No target was changed." and stored(rig) == long_target
        assert slash(rig, "land", "server") == "Back in orbit. Commands run on the server."
