"""Documented regression names must resolve to test functions."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ("dirtside-review-token-routes", "dirtside-seam-only-registration")


def test_cited_tests_exist():
    names = {node.name for path in (ROOT / "tests").rglob("*.py")
             for node in ast.walk(ast.parse(path.read_text()))
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")}
    documents = [ROOT / "README.md", ROOT / "docs/ARCHITECTURE.md"]
    for record in RECORDS:
        documents.extend((ROOT / "openspec/changes" / record).rglob("*.md"))
    missing = {str(path.relative_to(ROOT)): sorted(set(re.findall(r"\btest_[A-Za-z0-9_]+\b(?!\.py\b)",
                                                                path.read_text())) - names)
               for path in documents}
    assert not (missing := {path: names for path, names in missing.items() if names}), missing
