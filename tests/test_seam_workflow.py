"""The two-runner gate assembles the public method core, not an older gate."""
import subprocess
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


def test_gate_uses_public_release_and_method_patch():
    workflow = YAML(typ="safe").load(ROOT / ".github/workflows/check.yml")
    assert set(workflow["jobs"]) == {"gate"}
    job = workflow["jobs"]["gate"]
    assert job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "macos-latest"]
    steps = job["steps"]
    prepare = next(step["run"] for step in steps if step.get("name") == "Prepare the core checkout")
    assert "https://github.com/NousResearch/hermes-agent" in prepare
    assert "fetch --depth=1 origin 3b421578588243f920886e6fe79a6faa87ea026e" in prepare
    assert ("https://github.com/the-ai-entrepreneur-ai-hub/hermes-agent/commit/"
            "7dce8c38e8c998c52c4c139df340a0bffecc77e6.patch") in prepare
    assert 'git -C "$HERMES_SRC" apply --exclude=\'website/*\'' in prepare
    assert "--frozen" in prepare
    runs = "\n".join(step["run"] for step in steps if "run" in step)
    for command in ("-m pytest -q", "-m ruff check .", "tools/check_sizes.py",
                    "openspec validate --all --strict", "plugins doctor . --ci",
                    "plugins validate .", "tests/bench.py --loopback --report-only"):
        assert command in runs
    assert not any(step.get("continue-on-error") for step in steps)
    for step in steps:
        if "run" in step:
            checked = subprocess.run(["bash", "-n"], input=step["run"], text=True,
                                     capture_output=True, timeout=5)
            assert checked.returncode == 0, checked.stderr
