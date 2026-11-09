"""The rig's JSON pairing adapter for an installed, core-free console script."""
import json
import os
import subprocess
import sys


def main():
    executable, action = sys.argv[1:]
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    args = [executable, action]
    if action == "pair":
        data = json.load(sys.stdin)
        args += [data["gateway_url"], "--name", data["name"], "--code=" + data["code"]]
        return subprocess.call(args, env=env)
    os.execve(executable, args, env)


if __name__ == "__main__":
    raise SystemExit(main())
