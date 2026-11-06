"""Enforce the architecture's module budgets and hard file cap."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = {
    "model": 110, "protocol": 147, "registry": 188, "relay": 234, "client": 173, "local": 136,
    "environment": 116, "provider": 92, "auth": 60, "commands": 110, "prompt": 25, "cli": 159,
    "agent/config": 90, "agent/policy": 40, "agent/executor": 111, "agent/loop": 150,
}
BUDGETS = {f"dirtside/{name}.py": n for name, n in BUDGETS.items()} | {
    "__init__.py": 50, "dirtside/__init__.py": 50, "dashboard/plugin_api.py": 193,
    "tools/bench.py": 91, "tools/fake_device.py": 82, "tools/check_sizes.py": 30,
    "desktop/plugin.js": 280,
}

def main():
    files = [p for p in ROOT.rglob("*") if p.suffix in {".py", ".js"}
             and not any(s.startswith(".") or s in {"venv", "__pycache__"} for s in p.relative_to(ROOT).parts)]
    errors = []
    for path in files:
        name = path.relative_to(ROOT).as_posix()
        count = len(path.read_text().splitlines())
        if count > (budget := min(400, BUDGETS.get(name, 400))):
            errors.append(f"{name}: {count} lines exceeds {budget}")
    print("\n".join(errors) if errors else f"Size checks passed ({len(files)} source files).")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
