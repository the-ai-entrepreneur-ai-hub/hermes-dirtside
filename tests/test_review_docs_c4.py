"""Operator guidance names core authority and the device path limitation."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["README.md", "docs/ARCHITECTURE.md"])
def test_core_login_and_device_limits_are_explicit(name):
    text = (ROOT / name).read_text()
    for phrase in ("dashboard and Webapp sign-ins", "forwarded logins", "Windows",
                   "sid:", "not recognized as the host", "--code=<code>",
                   "core resolves file paths on the gateway; use the terminal for edits on a device"):
        assert phrase in text, phrase
    assert "--code <code>" not in text
    assert "login subjects are not the host" not in text
    assert "invalid existing device file must be repaired" not in text


def test_core_citations_do_not_look_repository_local():
    citations = re.compile(r"(?P<path>(?:[\w.-]+/)*[\w.-]+\.(?:py|tsx?|js|toml|md)):(?P<line>\d+)")
    found = []
    for file in ROOT.rglob("*.md"):
        if ".git" in file.parts:
            continue
        for match in citations.finditer(file.read_text()):
            path = match["path"]
            if not (ROOT / path).is_file():
                found.append(f"{file.relative_to(ROOT)}: {path}, line {match['line']}")
    assert not found, "\n".join(found)


def test_readme_promises_terminal_not_device_file_path_resolution():
    text = (ROOT / "README.md").read_text()
    assert "The terminal commands run on the machine you choose" in text
    assert "choice of where terminal commands run" in text
    assert "choosing a device, file tools," not in text
    manifest = (ROOT / "plugin.yaml").read_text()
    assert "Terminal commands use a chosen device; file paths resolve on the gateway." in manifest
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text()
    assert not [line for line in architecture.splitlines()
                if "so cached file operations also follow the target" in line]
