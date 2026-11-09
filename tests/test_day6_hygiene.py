"""Catalog admission and non-gating benchmark contracts."""
import os
import sys

import hermes_yaml as yaml
import pytest
from bench import main, report
import bench
from core_rig import CORE, ROOT
from hermes_cli.plugin_validate_private_imports import private_import_findings


def test_auth_types_use_the_exported_public_seam():
    hits = private_import_findings(ROOT)
    assert not any(hit.endswith(("DashboardAuthProvider", "TokenPrincipal")) for hit in hits)


def test_manifest_uses_only_supported_middleware_declarations():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    assert manifest["provides_middleware"] == ["tool_execution"]


@pytest.mark.parametrize("command", ['"$HERMES_SRC/venv/bin/hermes" plugins validate .',
                                    '"$HERMES_SRC/venv/bin/python" tools/bench.py --loopback --report-only'])
def test_ci_runs_catalog_validation_and_prints_non_gating_benchmark(command):
    workflow = yaml.safe_load((ROOT / ".github/workflows/check.yml").read_text())
    runs = "\n".join(step.get("run", "") for step in workflow["jobs"]["gate"]["steps"])
    assert command in runs


def test_report_only_keeps_every_failed_threshold_visible(capsys):
    metrics = (100, 100, 0, 100)
    assert report(metrics, report_only=True) == 0
    assert capsys.readouterr().out.count("| FAIL |") == 4
    assert report(metrics) == 1
    assert capsys.readouterr().out.count("| FAIL |") == 4


@pytest.mark.parametrize("integrity_error", [False, True])
def test_report_only_cli_ignores_only_threshold_misses(monkeypatch, capsys, integrity_error):
    monkeypatch.setattr(sys, "argv", ["bench.py", "--loopback", "--report-only"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(bench.tempfile, "tempdir", bench.tempfile.tempdir)
    for name in ("HOME", "HERMES_HOME", "HERMES_RUNTIME_DIR", "TMPDIR", "TERMINAL_TEMP_DIR"):
        monkeypatch.setenv(name, os.environ[name])
    monkeypatch.setenv("HERMES_SRC", str(CORE))
    def measure(root):
        if integrity_error:
            raise RuntimeError("10 MB transfer was incomplete or altered")
        return 100, 100, 0, 100
    monkeypatch.setattr(bench, "measure", measure)
    if integrity_error:
        with pytest.raises(RuntimeError, match="incomplete or altered"):
            main()
    else:
        assert main() == 0
        assert capsys.readouterr().out.count("| FAIL |") == 4
