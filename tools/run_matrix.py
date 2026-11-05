"""Own the rehearsal processes, retain row evidence, and clean up on failure.

Loopback: scripts/two_machine_matrix.sh --loopback

For two machines, provide --gateway-url https://... --port 9119 --device laptop
and --device-command 'ssh HOST /path/to/venv/bin/python /path/to/tools/run_matrix.py
--device-worker /absolute/private/rehearsal-home'. The gateway URL must already
forward to the loopback listener on the requested port. The same core and plugin
must exist remotely. Pair credentials travel on stdin, not in the remote command.
The owned device worker stops its agent on stdin EOF. No remote HTTP control
endpoints or service-manager operations are installed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from core_rig import ROOT, Rig, stop_process
from matrix_cases import ROWS


def run_rows(root, evidence, rows=ROWS, rig_factory=Rig, **options):
    evidence.mkdir(parents=True, exist_ok=True)
    passed = 0
    for name, check in rows:
        started = time.monotonic()
        try:
            with rig_factory(root / name, **options) as rig:
                rig.pair().start_agent().choose()
                detail = check(rig)
            status = "PASS"
            passed += 1
        except Exception:
            status, detail = "FAIL", traceback.format_exc()
        elapsed = time.monotonic() - started
        transcript = f"{status} {name} ({elapsed:.2f}s)\n{detail}\n"
        (evidence / f"{name}.txt").write_text(transcript)
        print(f"{status} {name} ({elapsed:.2f}s)", flush=True)
    print(f"Matrix: {passed}/{len(rows)} passed", flush=True)
    print(f"Evidence: {evidence}", flush=True)
    return 0 if passed == len(rows) else 1


def device_worker(state, action):
    state = state.expanduser().resolve()
    if state == Path.home() / ".hermes":
        raise ValueError("the rehearsal cannot use the real Hermes home")
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    for key, path in dict(HOME=state / "user", HERMES_HOME=state, TMPDIR=state / "tmp",
                          XDG_RUNTIME_DIR=state / "run").items():
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.environ[key] = str(path)
    core = Path(os.environ.get("HERMES_SRC", ROOT.parent / "hermes-agent-main")).resolve()
    os.environ["PYTHONPATH"] = os.pathsep.join(map(str, (core, ROOT)))
    sys.path[:0] = [str(core), str(ROOT)]
    if action == "pair":
        from dirtside.cli import pair
        pair(argparse.Namespace(**json.load(sys.stdin)))
        return 0
    proc = subprocess.Popen([sys.executable, "-m", "dirtside.agent"], stdin=subprocess.DEVNULL)
    def eof():
        sys.stdin.buffer.read()
        stop_process(proc)
    threading.Thread(target=eof, daemon=True).start()
    previous = {sig: signal.signal(sig, lambda *_: stop_process(proc))
                for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return proc.wait()
    finally:
        stop_process(proc)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loopback", action="store_true")
    parser.add_argument("--gateway-url", help="Existing external URL forwarded to this rig's loopback port")
    parser.add_argument("--port", type=int, help="Loopback gateway port, default ephemeral or 9119 for two machines")
    parser.add_argument("--device", default="matrix-device")
    parser.add_argument("--device-command", help="Owned remote worker command prefix, split as shell words")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--device-worker", type=Path, help="Remote-only private rehearsal home")
    parser.add_argument("action", nargs="?", choices=("pair", "serve"))
    args = parser.parse_args(argv)
    if args.device_worker:
        if not args.action:
            parser.error("--device-worker requires pair or serve")
        return device_worker(args.device_worker, args.action)
    if args.loopback and (args.gateway_url or args.device_command):
        parser.error("--loopback cannot use an external gateway or device")
    if not args.loopback and not (args.gateway_url and args.device_command):
        parser.error("choose --loopback or provide --gateway-url and --device-command")
    now = datetime.now(timezone.utc)
    evidence = (args.evidence or ROOT / "evidence" / now.strftime("%Y-%m-%d") /
                (now.strftime("%H%M%S") + f"-{os.getpid()}")).resolve()
    private = ROOT / ".notes" / "test-home" / "tmp"
    private.mkdir(parents=True, exist_ok=True)
    options = dict(name=args.device, url=args.gateway_url, device_command=shlex.split(args.device_command or ""),
                   port=args.port if args.port is not None else (0 if args.loopback else 9119))
    def terminated(signum, _):
        raise SystemExit(128 + signum)
    previous = signal.signal(signal.SIGTERM, terminated)
    try:
        with tempfile.TemporaryDirectory(prefix="matrix-", dir=private) as home:
            return run_rows(Path(home), evidence, **options)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
