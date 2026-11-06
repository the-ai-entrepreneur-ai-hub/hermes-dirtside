"""Keep the architecture's source contracts tied to the shipped modules."""
import ast
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]


def test_architecture_lists_actual_runtime_core_imports():
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text()
    modules = ("agent", "gateway", "hermes_cli", "hermes_constants", "plugins", "tools")
    paths = [ROOT / "__init__.py", *ROOT.glob("dirtside/**/*.py"), *ROOT.glob("dashboard/*.py")]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and not node.level and node.module.split(".")[0] in modules:
                for name in node.names:
                    assert f"{node.module}.{name.name}" in architecture, (path.name, node.module, name.name)


def test_architecture_size_budgets_match_the_size_gate():
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text()
    budgets = runpy.run_path(str(ROOT / "tools/check_sizes.py"))["BUDGETS"]
    rows = {line.split("|")[1].strip(" `"): line for line in architecture.splitlines()
            if line.startswith("| `")}
    for path, budget in budgets.items():
        assert rows[path].rstrip().endswith(f"| {budget} |"), (path, budget)


def test_architecture_resolver_and_owner_boundary_match_runtime():
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text()
    section = architecture.split("## A7. Provider and target resolution\n", 1)[1].split("## A8.", 1)[0]
    snippet = section.split("```python\n", 1)[1].split("```", 1)[0]
    documented = next(node for node in ast.parse(snippet).body
                      if isinstance(node, ast.FunctionDef) and node.name == "resolve_target")
    runtime = next(node for node in ast.parse((ROOT / "dirtside/provider.py").read_text()).body
                   if isinstance(node, ast.FunctionDef) and node.name == "resolve_target")
    assert ast.dump(documented) == ast.dump(runtime)
    assert 'ctx.get_config("default_target", "server") or "server"' in section
    assert "Bare status calls `resolve_target(..., require_contact=False)`" in section
    assert "Only the first accepted device message in a new owner performs stale-history cleanup" in architecture
