"""Enforce the architecture's module budgets and hard file cap."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = {
    "backend": 22, "access": 112, "model": 118, "protocol": 147, "registry": 225, "relay": 239, "client": 198, "local": 152, "readiness": 8,
    "environment": 124, "provider": 183, "auth": 96, "commands": 103, "prompt": 38, "awareness": 35, "cli": 194, "agent/platform": 24,
    "agent/home": 22, "agent/console": 13, "agent/config": 100, "agent/policy": 40, "agent/executor": 115, "agent/loop": 150,
}
BUDGETS = {f"dirtside/{name}.py": n for name, n in BUDGETS.items()} | {
    "__init__.py": 50, "dirtside/__init__.py": 58, "dashboard/plugin_api.py": 227,
    "tests/bench.py": 92, "tools/fake_device.py": 82, "tools/check_sizes.py": 30,
    "desktop/plugin.js": 280, "tools/termux_forward.py": 62, "tools/termux_check.py": 157, "dirtside/shortcuts.py": 20,
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
