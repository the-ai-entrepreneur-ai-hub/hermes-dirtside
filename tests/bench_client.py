"""Non-gating local-worker latency through a separately mounted owner."""
from pathlib import Path
from core_rig import Core
from bench import percentile, timed, report as report_in_process

def measure(root):
    from tools.environments.local import LocalEnvironment
    from dirtside.client import Client
    from dirtside.environment import DirtsideEnvironment
    from dirtside.registry import Registry
    from dirtside.relay import Relay
    with Core(root / "client-owner", user_home=root) as owner:
        owner.call("fake_device", root=str(root))
        assert owner.http("GET", "/devices").status_code == 200
        registry = Registry(Path(owner.info["registry"]))
        relay = Relay(registry)
        relay._client = Client(relay)
        local = LocalEnvironment(cwd=str(root), timeout=30)
        remote = DirtsideEnvironment(relay, registry.active_device("fake"), "bench", "bench", str(root), 30)
        try:
            timed(local, "pwd"), timed(remote, "pwd")
            samples = [1000 * (-timed(local, "pwd")[1] + timed(remote, "pwd")[1]) for _ in range(50)]
            return percentile(samples, .50), percentile(samples, .95)
        finally:
            remote.cleanup()
            local.cleanup()
            relay._client.http.close()

def report(metrics):
    for value, name in zip(metrics, ("pwd client added p50", "pwd client added p95"), strict=True):
        print(f"| {name} | {value:.2f} ms | report only | INFO |")

def finish(root, metrics, report_only):
    result = report_in_process(metrics, report_only=report_only)
    report(measure(root))
    return result
