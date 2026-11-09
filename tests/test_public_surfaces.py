"""Catalog admission uses the real core lint on an intended source export."""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hermes_cli.plugin_validate_private_imports import (
    private_attribute_findings, private_import_findings,
)
from tools.plugin_guard import scan_plugin, should_allow_plugin_install

ROOT = Path(__file__).resolve().parents[1]
TRANSITIONAL = [
    ("dirtside/auth.py", "hermes_cli.dashboard_auth.token_auth.register_token_route"),
    ("dirtside/backend.py", "tools.environments.local.LocalEnvironment"),
    ("dirtside/environment.py", "tools.environments.base.EnvironmentConnectionError"),
]


@pytest.fixture
def clean_export(tmp_path):
    if not (ROOT / ".git").exists():
        return ROOT  # The baseline run is already a fresh git archive.
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", "-z"],
                            capture_output=True, check=True)
    exported = tmp_path / "export"
    exported.mkdir()
    for name in result.stdout.decode().split("\0"):
        source = ROOT / name
        if name and source.is_file():
            target = exported / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return exported


def test_private_imports_are_exact_transitional_set(clean_export):
    findings = private_import_findings(clean_export)
    sites = [(location.rsplit(":", 1)[0], target)
             for location, target in (site.split(" ", 1) for site in findings)]
    assert sorted(sites) == TRANSITIONAL, "\n".join(findings)
    assert private_attribute_findings(clean_export) == []


def test_community_install_allows_clean_export(clean_export):
    scan = scan_plugin(clean_export, source="community/dirtside")
    assert scan.trust_level == "community"
    allowed, reason = should_allow_plugin_install(scan)
    findings = "\n".join(f"{f.severity} {f.file}:{f.line} {f.pattern_id}" for f in scan.findings)
    assert allowed is True, f"{reason}\n{findings}"


def test_development_entrypoints(clean_export, tmp_path):
    for name in ("core_runtime.py", "bench.py", "bench_client.py"):
        assert not (clean_export / "tools" / name).exists()
        assert (clean_export / "tests" / name).is_file()
    assert not [p.relative_to(clean_export) for p in clean_export.rglob("test_*.py")
                if not {"test", "tests"}.intersection(p.relative_to(clean_export).parts[:-1])]
    help_run = subprocess.run([sys.executable, str(clean_export / "tests" / "bench.py"), "--help"],
                              cwd=clean_export, capture_output=True, text=True, timeout=20)
    assert help_run.returncode == 0 and "--loopback" in help_run.stdout, help_run.stderr
    spec = importlib.util.spec_from_file_location("surface_rig", clean_export / "tools" / "core_rig.py")
    rig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rig)
    with rig.Core(tmp_path / "worker", worker=True) as worker:
        result = worker.call("terminal", args={"command": "printf relocated-core", "timeout": 5})
        assert result["exit_code"] == 0 and result["output"] == "relocated-core", result


def test_review_documentation(clean_export):
    readme = (clean_export / "README.md").read_text()
    status = readme.split("## Status\n", 1)[1].split("## License", 1)[0]
    for name in ("token_auth", "LocalEnvironment", "EnvironmentConnectionError"):
        assert name in status
    for term in ("env_passthrough", "SSH_AUTH_SOCK", "WSL_INTEROP", "DISPLAY",
                 "policy --env-passthrough", "policy --clear-env-passthrough",
                 "owners", "platform:user_id", "current turn", "ACP"):
        assert term in readme
    collection = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                                cwd=clean_export, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=30)
    assert collection.returncode == 0, collection.stdout + collection.stderr
    count = re.search(r"(\d+) tests collected", collection.stdout).group(1)
    assert f'alt="{count} tests passing"' in readme
    assert f"tests/                    {count} tests:" in readme
