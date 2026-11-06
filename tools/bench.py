"""Signed loopback measurements, with separate non-gating local-client latency."""
import argparse
import math
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LIMITS = (("pwd added p50", 15, "ms", True), ("pwd added p95", 40, "ms", True),
          ("10 MB output", 8, "MB/s", False), ("kill to tool return", 50, "ms", True))

def percentile(samples, fraction):
    return sorted(samples)[math.ceil(len(samples) * fraction) - 1]

def report(metrics, *, report_only=False):
    print("| Measurement | Result | Loopback target | Status |\n|---|---:|---:|---|")
    passed = []
    for value, (name, limit, unit, upper) in zip(metrics, LIMITS, strict=True):
        ok = value <= limit if upper else value >= limit
        passed.append(ok)
        print(f"| {name} | {value:.2f} {unit} | {'<=' if upper else '>='} {limit} {unit} | {'PASS' if ok else 'FAIL'} |")
    return 0 if report_only or all(passed) else 1

def timed(env, command):
    start = time.perf_counter()
    result = env.execute(command, bounded_capture=False)
    elapsed = time.perf_counter() - start
    if result["returncode"] != 0:
        raise RuntimeError("benchmark command failed")
    return result, elapsed

def cancellation(remote, relay):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(remote.execute, "head -c 65536 /dev/zero; sleep 30", timeout=10)
        deadline, handle = time.monotonic() + 5, None
        while handle is None and time.monotonic() < deadline:
            with relay._condition:
                handle = next((h for h in relay.handles.values() if relay.tail(h.req.id)), None)
            time.sleep(0.001)
        if handle is None:
            raise RuntimeError("cancellation command never started")
        start = time.perf_counter()
        handle.kill()
        result = future.result(timeout=2)
        elapsed = (time.perf_counter() - start) * 1000
        if result["returncode"] != 130:
            raise RuntimeError("cancelled tool did not return exit 130")
        return elapsed

def measure(root):
    from tools.environments.local import LocalEnvironment
    from nacl.signing import SigningKey
    from dirtside.environment import DirtsideEnvironment
    from dirtside.protocol import DeviceHello
    from dirtside.registry import Registry
    from dirtside.relay import Relay
    from fake_device import FakeDevice
    registry, key = Registry(root / "registry.db"), SigningKey.generate()
    code = registry.mint("loopback", int(time.time()))
    hello = DeviceHello(bytes(key.verify_key), "loopback", sys.platform, "", str(root), str(root), "0.1.0")
    device, token = registry.complete_pairing("loopback", hello, int(time.time()), code=code)
    relay, local = Relay(registry), LocalEnvironment(cwd=str(root), timeout=30)
    with FakeDevice(relay, device, token, key):
        remote = DirtsideEnvironment(relay, device, "bench", "bench", str(root), 30)
        timed(local, "pwd"), timed(remote, "pwd")
        samples = [1000 * (-timed(local, "pwd")[1] + timed(remote, "pwd")[1]) for _ in range(50)]
        output, seconds = timed(remote, "head -c 10000000 /dev/zero")
        if output["output"] != "\0" * 10_000_000:
            raise RuntimeError("10 MB transfer was incomplete or altered")
        metrics = percentile(samples, .50), percentile(samples, .95), 10 / seconds, cancellation(remote, relay)
        remote.cleanup()
    local.cleanup()
    return metrics
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loopback", action="store_true", required=True)
    parser.add_argument("--report-only", action="store_true", help="Print threshold misses without failing")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path[:0] = [os.environ["HERMES_SRC"], str(Path(__file__).resolve().parents[1])]
    with tempfile.TemporaryDirectory(prefix="dirtside-bench-") as temporary:
        tempfile.tempdir = temporary
        for name in ("HOME", "HERMES_HOME", "HERMES_RUNTIME_DIR", "TMPDIR", "TERMINAL_TEMP_DIR"):
            os.environ[name] = temporary
        print("Signed in-process loopback; 50 paired pwd samples; 10,000,000 verified bytes; excludes HTTP/LAN.")
        from bench_client import finish
        return finish(Path(temporary), measure(Path(temporary)), args.report_only)
if __name__ == "__main__":
    raise SystemExit(main())
