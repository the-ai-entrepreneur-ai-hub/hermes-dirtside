# Dirtside architecture

Reference for the engineer building Dirtside. Written 2026-11-05 against the contracts verified in `DIRTSIDE-PLAN.md` section 17, then revised after a fresh-context review against the same source files. The plan says what and when. This document says how, in enough detail that the first commit has no design left to make. Part A is reference (what exists, what it owns, what it promises). Part B is explanation (why it is shaped this way, with the alternatives that lost). Nothing here is built.

Two rules govern every choice below. Build the smallest thing that does the job, on top of what Hermes already provides. Put the domain in data structures, so the code has few branches and no scattered modes.

---

# Part A. Reference

## A1. Languages and stack

| Layer | Language and runtime | Why this and nothing else |
|---|---|---|
| Gateway plugin (provider, relay, registry, commands, auth) | Python, the interpreter Hermes runs on (3.11 assumed, confirm against Hermes' `pyproject.toml` on day 0) | plugins load in-process; no choice |
| Device agent (`hermes dirtside serve`) | the same Python, the same package, run through the device's own Hermes install | one codebase, one protocol module, nothing to drift |
| Relay HTTP routes | FastAPI `APIRouter` in `dashboard/plugin_api.py` | the only route surface Hermes mounts for plugins |
| Desktop half | JavaScript ES module, React through `jsx()` from `react/jsx-runtime`, `@hermes/plugin-sdk` | the loader takes uncompiled ESM only |
| Storage | one SQLite file under `plugin_data_dir("dirtside")`, WAL | survives `hermes plugins update`; no ORM |
| Signatures | Ed25519 through PyNaCl, pinned `pynacl>=1.5,<2` | the one new dependency; upper bound per catalog rule 10 |
| HTTP client on the device | `httpx`, present in every Hermes install | installed dependency beats a new one |
| Tests | pytest | what the official Singularity plugin uses |
| Lint | ruff with `mccabe.max-complexity = 8`; `tools/check_sizes.py` fails any Python file over 400 lines or `plugin.js` over 400 | the no-spaghetti and no-giant-file rules as checks, not prose |

Not used, on purpose: Pydantic request models (signatures are verified over canonical JSON of the parsed dict, then one `parse_*` function per message kind produces a frozen dataclass), WebSockets (long-poll in v1), asyncio inside domain code (threads and one `Condition`), plugin events (the pane polls), a settings page (`config_schema` already renders the form), any logging or retry framework.

## A2. Domain model

All types live in `dirtside/model.py`. Frozen dataclasses, `NewType` ids, no I/O.

```python
DeviceId   = NewType("DeviceId", str)     # 16 random bytes, hex
SessionKey = NewType("SessionKey", str)   # see session_identity() in A12
RequestId  = NewType("RequestId", str)    # "r_" + 12 random bytes, hex

@dataclass(frozen=True)
class Device:                              # paired, not revoked, not expired; nothing else is a Device
    id: DeviceId; name: str; pubkey: bytes
    os: str; arch: str; home: str; temp_dir: str; agent_version: str

@dataclass(frozen=True)
class Pending:                             # a minted pairing code, until the device completes pairing
    name: str; expires_at: int
Credential = Pending | Device              # what a bearer token resolves to

@dataclass(frozen=True)
class Server: ...
@dataclass(frozen=True)
class OnDevice:
    device: Device
Target = Server | OnDevice                 # where a conversation's commands run

class RequestState(Enum):
    QUEUED = "queued"; RUNNING = "running"; FINISHED = "finished"
    REFUSED = "refused"; CANCELLED = "cancelled"; LOST = "lost"
TERMINAL = frozenset({RequestState.FINISHED, RequestState.REFUSED, RequestState.CANCELLED, RequestState.LOST})

@dataclass(frozen=True)
class ExecRequest:                         # gateway-side record; the wire form is smaller (A8)
    id: RequestId; device_id: DeviceId; session_key: SessionKey; task_id: str
    command: str                           # the model's command, for policy and the pane
    script: str                            # the wrapped bash script BaseEnvironment produced
    login: bool; timeout_s: int; stdin: str | None; cwd: str

@dataclass(frozen=True)
class Outcome:                             # a terminal report, from the device or from the relay itself
    state: RequestState; exit_code: int; duration_ms: int; truncated: bool; reason: str

@dataclass(frozen=True)
class Policy:                              # parsed once on the device at its config boundary
    deny_patterns: tuple[re.Pattern, ...]; max_timeout_s: int; max_output_bytes: int; max_parallel: int

@dataclass(frozen=True)
class Refused:
    reason: str
Decision = None | Refused                  # None means allowed

OFFLINE_AFTER_S = 45; LOST_GRACE_S = 5; POLL_HOLD_S = 25; PAIR_TTL_S = 600
CHUNK_BYTES = 65536; FLUSH_MS = 200; FEED_BLOCK_S = 10; PANE_TAIL_BYTES = 4096; MAX_OUTPUT_BYTES = 64 << 20
```

What the types forbid:

- A `Target` is `Server` or `OnDevice` with a real `Device`. No string target, no "unknown device", no boolean.
- A `Device` is paired and active by construction. Revoked and pending rows never leave the registry as `Device`.
- Wire types live in `protocol.py`: `DeviceHello(pubkey, name, os, arch, home, temp_dir, agent_version)`, `WireExec(id, command, script, login, timeout_s, stdin, cwd)` and `Chunk(id, seq, data: bytes)`. `RequestRow` is the registry's read model of one `requests` row (A4).
- Online is derived, never stored: `last_seen[device] >= now - OFFLINE_AFTER_S`, with `last_seen` in relay memory. A gateway restart makes every device offline until its next poll, which is the truth.
- Lost is derived the same way, per request, by the thread that is already waiting (A5). There is no sweeper.
- Device policy is parsed once at the device's boundary; `deny_patterns` are compiled there. `evaluate()` never sees raw config.

## A3. Modules, ownership, size budget

Dependency direction is top to bottom. No module imports one below it except through the listed edges. Sizes are budgets the size check enforces.

| Module | Owns | Depends on | Budget |
|---|---|---|---|
| `dirtside/model.py` | the types and constants above | stdlib | 110 |
| `dirtside/protocol.py` | `Envelope`, canonical JSON, `sign`, `verify`, `ReplayGuard`, one `parse_*` per message kind, `PROTOCOL_VERSION = 1` | model, nacl | 140 |
| `dirtside/registry.py` | the SQLite boundary: devices (pending, paired, revoked), targets, request log | model, sqlite3 | 180 |
| `dirtside/relay.py` | all live state under one `Condition`: handles, `last_seen`, cancels; `submit`, `next`, `feed`, `close`, `kill`, `touch`, `is_online`, `revoke` | model, registry, threading | 200 |
| `dirtside/environment.py` | `DirtsideEnvironment(BaseEnvironment)`, `RemoteProcessHandle` | relay, `tools.environments.base` | 110 |
| `dirtside/provider.py` | `DirtsideProvider`, `resolve_target()`, `session_identity()` | relay, registry, `agent.terminal_env_provider`, `tools.environments.local`, `gateway.session_context` | 90 |
| `dirtside/auth.py` | `DirtsideDeviceAuth(DashboardAuthProvider)`, token route registration | registry, `hermes_cli.dashboard_auth` | 60 |
| `dirtside/commands.py` | `/dirtside` handlers, text in and text out | relay, registry, provider (`session_identity`) | 110 |
| `dirtside/prompt.py` | `current_target_section()` | registry, provider (`session_identity`) | 25 |
| `dirtside/cli.py` | `hermes dirtside serve`, `pair`, `status`, `install-service` | agent/*, argparse | 140 |
| `dirtside/agent/config.py` | `DeviceConfig` read and atomic write (`device.json`, 0600) | model, protocol | 90 |
| `dirtside/agent/policy.py` | `evaluate(command, policy) -> Decision`, pure | model | 40 |
| `dirtside/agent/executor.py` | `run(request, policy, send) -> Outcome`, process groups, chunking, cancel | model, subprocess | 110 |
| `dirtside/agent/loop.py` | poll, backoff, dispatch, bounded parallelism, retrying posts | config, policy, executor, protocol, httpx | 150 |
| `dashboard/plugin_api.py` | routes: resolve bearer, verify, parse, one relay or registry call | protocol, relay, registry | 140 |
| `desktop/plugin.js` | pane, chip | `@hermes/plugin-sdk` | 280 |
| `__init__.py` | `register(ctx)` wiring | gateway modules | 50 |
| `tools/bench.py` | p50/p95 added latency for `pwd`, throughput, cancel time, against the fake device or a real gateway; exits non-zero when an A15.1 target is missed | httpx, statistics | 90 |
| `tools/fake_device.py` | an in-process device for tests | agent/executor, relay | 80 |
| `tools/check_sizes.py` | the size check | stdlib | 30 |

Core imports, in full, and where each is allowed: `agent.terminal_env_provider.TerminalEnvironmentProvider` (provider), `tools.environments.base.BaseEnvironment` and `EnvironmentConnectionError` (environment, provider), `tools.environments.local.LocalEnvironment` (provider), `gateway.session_context.get_session_env` (provider), `plugins.plugin_storage.plugin_data_dir` (`__init__`), `hermes_cli.dashboard_auth.base.DashboardAuthProvider` and `TokenPrincipal` (auth), `hermes_cli.dashboard_auth.token_auth.register_token_route` (auth). Nothing else from Hermes is imported, and nothing from Hermes is ever monkeypatched.

## A4. Registry (the SQLite boundary, and only a log for requests)

`Registry(path)` opens one connection per thread (thread-local), WAL, `busy_timeout = 5000`. The shared connection from `plugin_db()` is never used. Every public method is one transaction and returns a model type or `None`, never a row.

```sql
CREATE TABLE devices (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash BLOB NOT NULL,
  pubkey BLOB, os TEXT, arch TEXT, home TEXT, temp_dir TEXT, agent_version TEXT,
  created_at INTEGER NOT NULL, expires_at INTEGER, revoked_at INTEGER
);                                   -- pubkey NULL and expires_at set = pending; pubkey set and expires_at NULL = paired
CREATE UNIQUE INDEX devices_active_name ON devices(name) WHERE revoked_at IS NULL AND pubkey IS NOT NULL;
CREATE TABLE targets (session_key TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id), set_at INTEGER NOT NULL);
CREATE TABLE requests (
  id TEXT PRIMARY KEY, device_id TEXT NOT NULL, session_key TEXT NOT NULL, task_id TEXT NOT NULL,
  state TEXT NOT NULL, preview TEXT NOT NULL, created_at INTEGER NOT NULL,
  finished_at INTEGER, exit_code INTEGER, reason TEXT
);
```

The relay's Ed25519 seed is a 0600 file next to the database, `relay.key`, the same shape as `device.json` on the device.

```python
class Registry:
    def mint(self, name: str, now: int) -> str                        # pending row, token_hash = sha256(code); returns the code once
    def credential_for(self, bearer: str, now: int) -> Credential | None   # constant-time compare; expired pending rows are None
    def complete_pairing(self, name: str, hello: DeviceHello, now: int) -> tuple[Device, str]
        # one transaction: revoke any paired device with this name, set pubkey and facts, rotate the token, clear expires_at; returns (device, bearer) once
    def active_device(self, name: str) -> Device | None
    def device_by_id(self, device_id: DeviceId) -> Device | None
    def revoke(self, name: str, now: int) -> Device | None
    def set_target(self, session_key: SessionKey, device_id: DeviceId | None) -> None   # None clears (server)
    def target_device_id(self, session_key: SessionKey) -> DeviceId | None
    def log(self, req: ExecRequest) -> None                           # INSERT, state queued, preview = command[:120]
    def close(self, request_id: RequestId, outcome: Outcome, now: int) -> None   # plain UPDATE; the relay already decided
    def mark_stale_lost(self, now: int) -> None                       # at register(): UPDATE requests SET state='lost' WHERE state IN ('queued','running')
    def recent(self, limit: int, session_key: SessionKey | None = None) -> list[RequestRow]
```

## A5. Relay (all live state, one lock)

The gateway is one process (`plugins.isolation: in_process` is required for any terminal provider), so a lock in that process is the strongest and simplest arbiter of request state. The relay holds `handles: dict[RequestId, RemoteProcessHandle]`, `last_seen: dict[DeviceId, float]` `cancels: dict[DeviceId, set[RequestId]]` and `tails: dict[RequestId, bytearray]` (the last `PANE_TAIL_BYTES` of each live request, for the pane) under one `threading.Condition`. Nothing else in the gateway holds request state.

```python
class Relay:
    def __init__(self, registry: Registry): ...
    # gateway side, tool threads
    def submit(self, req: ExecRequest) -> RemoteProcessHandle   # registry.log; handle in QUEUED; notify
    def kill(self, request_id: RequestId) -> None                # close(CANCELLED, 130) now; add to cancels[device] for the device's next poll
    def is_online(self, device_id: DeviceId) -> bool
    def tail(self, request_id: RequestId) -> bytes                # the pane's live output tail
    def revoke(self, device_id: DeviceId) -> None                # close(CANCELLED, 130) every live handle of that device
    # device side, route workers
    def touch(self, device_id: DeviceId) -> None                 # last_seen = now
    def next(self, device_id: DeviceId, wait_s: float) -> tuple[ExecRequest | None, list[RequestId]]
        # blocks on the Condition up to wait_s; returns the oldest QUEUED request for that device (now RUNNING) and the pending cancels
    def feed(self, request_id: RequestId, seq: int, data: bytes) -> bool   # False when terminal or unknown (route answers 410); drops seq <= last
    def close(self, request_id: RequestId, outcome: Outcome) -> bool       # idempotent; the one place a request becomes terminal
```

`close()` is the single terminal transition. Under the lock it checks the handle is not terminal, records the state, closes the pipe's write end, sets the exit code, and signals the handle. Outside the lock it calls `registry.close()`. A second `close()` for the same request returns `False` and does nothing. This one critical section replaces the plan's database compare-and-set, the sweep thread and the "who closes the pipe" question.

`feed()` writes the whole chunk to the pipe outside the lock. The first draft used a non-blocking write and dropped what did not fit. A 64 KB chunk is exactly one pipe buffer on macOS (measured, A15.1), so a second chunk that lands before core's drain thread has been scheduled cannot fit, and a writer that ignores the short count drops the remainder. The write end stays non-blocking (a blocking `os.write` cannot be bounded), and `feed()` loops on `select` for writability in one second slices, re-checking the handle's terminal state each slice and giving up after `FEED_BLOCK_S` in total. The device posts one chunk at a time and waits for the 2xx, so a slow reader slows the device and nothing is dropped; a cancel or close releases the worker within a second, because closing the write fd under a parked writer would not deliver EOF on its own. A feed that cannot finish inside the bound means the gateway stopped reading; the relay then closes the request as `LOST` with reason `gateway stopped reading output`, and the device's next post gets 410 and kills the process group. `feed()` also appends to `tails[request_id]`, trimmed to `PANE_TAIL_BYTES`, under the lock.

Poll handler: `loop.run_in_executor(POLL_POOL, relay.next, device_id, POLL_HOLD_S)` with `POLL_POOL = ThreadPoolExecutor(max_workers=16)` owned by the plugin. The default executor is shared with the rest of the gateway; a 25 second hold per device would starve it. The chunk route runs `relay.feed` on that same pool, because a feed can block for up to `FEED_BLOCK_S` and the default executor (`min(32, cpu_count + 4)` threads shared with the whole gateway) must never hold it. The remaining routes are short and use `asyncio.to_thread`.

Lost detection: core's `_wait_for_process` never calls the handle's `wait()`; it calls `poll()` in a loop that starts at 5 ms and backs off to 200 ms, so `poll()` is the detector and must stay a plain read: the returncode, then `now - last_seen[device] > OFFLINE_AFTER_S + LOST_GRACE_S`, and on that condition `relay.close(id, Outcome(LOST, 124, ...))`. `wait()` loops on `_done.wait(1.0)` with the same check for the few callers that use it. QUEUED and RUNNING are covered alike, and the thread doing the detection is the one already waiting.

## A6. Environment and process handle

```python
class RemoteProcessHandle:                 # the ProcessHandle duck type from tools/environments/base_output.py
    stdout: IO[bytes]                      # read end of os.pipe(); core's drain decodes incrementally, once
    def poll(self) -> int | None           # returncode when terminal, with the lost check
    def wait(self, timeout=None) -> int    # loops _done.wait(1.0) with the lost check
    def kill(self) -> None                 # relay.kill(id)
    @property
    def returncode(self) -> int | None

class DirtsideEnvironment(BaseEnvironment):
    _stdin_mode = "payload"                # verified: tools/environments/base.py line 272; stdin rides the request
    _persistent = True                     # verified: terminal_tool_lifecycle.py line 270 keys per-turn teardown on this name
    _passwordless_sudo_probe_supported = False

    def __init__(self, relay, device, session_key, task_id, cwd, timeout):
        ...; super().__init__(cwd=device.home if cwd == "~" else cwd, timeout=timeout); self.init_session()
    def get_temp_dir(self): return self._device.temp_dir
    def execute(self, command, cwd="", **kwargs):
        self._command = command            # the model's command, before wrapping; one line, for policy and the pane
        return super().execute(command, cwd, **kwargs)
    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None):
        return self._relay.submit(ExecRequest(..., command=self._command, script=cmd_string, login=login, timeout_s=timeout, stdin=stdin_data, cwd=self.cwd))
    def cleanup(self): pass                # nothing is held on the device between commands; core calls this on idle reap and session close
```

`_persistent = True` matters: without it the agent loop tears the environment down after every turn, `init_session()` runs the snapshot bootstrap on the device again, and `cd` and `export` do not survive between turns. The idle reaper still cleans up after 300 seconds idle.

## A7. Provider and target resolution

```python
def session_identity() -> SessionKey:
    return SessionKey(get_session_env("HERMES_SESSION_KEY") or get_session_env("HERMES_SESSION_ID"))

def resolve_target(session_key, is_cron: bool, default_target: str, registry, relay) -> Target:
    chosen = registry.target_device_id(session_key)
    default = None if is_cron or default_target == "server" else registry.active_device(default_target)
    device = registry.device_by_id(chosen) if chosen else default
    if device is None and chosen:
        raise EnvironmentConnectionError("Dirtside: this conversation's device is no longer paired.", retry_hint="Run /dirtside use server, or pair the device again.")
    if device is None:
        return Server()
    if not relay.is_online(device.id):
        raise EnvironmentConnectionError(f"Dirtside: device '{device.name}' is offline.", retry_hint="Start `hermes dirtside serve` on it, or run /dirtside use server. Nothing was run on the server.")
    return OnDevice(device)

class DirtsideProvider(TerminalEnvironmentProvider):
    name = "dirtside"; display_name = "Dirtside (your own devices)"
    is_remote = True; is_container = False         # the ABC derives skip_container_guards from is_container, so approvals stay on; a test pins it
    default_cwd = property(lambda self: "~")
    def is_available(self): return True
    def create_environment(self, *, cwd, timeout, task_id="default", image=None, container_config=None, **kwargs):
        key = session_identity()
        target = resolve_target(key, get_session_env("HERMES_CRON_SESSION") == "1", self._default_target, self._registry, self._relay)
        match target:
            case Server(): return LocalEnvironment(cwd="" if cwd == "~" else cwd, timeout=timeout)
            case OnDevice(device): return DirtsideEnvironment(self._relay, device, key, task_id, cwd, timeout)
```

`resolve_target` has a six-row truth table in its test (chosen or not, cron or not, default or not, online or not). `create_environment` has no branch of its own.

## A8. Protocol

One `Envelope` shape in both directions. `protocol.py` is imported by the gateway and by the device, so there is one implementation of canonical JSON, signing and replay checks.

```python
@dataclass(frozen=True)
class Envelope:
    v: int; kind: str; sender: str; ts: int; nonce: str; body: dict; sig: bytes

def canonical(payload: dict) -> bytes      # json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def sign(key: SigningKey, kind: str, sender: str, body: dict) -> dict
def verify(pubkey: VerifyKey, wire: dict, now: int, guard: ReplayGuard | None) -> Envelope   # raises ProtocolError
class ReplayGuard: ...                     # window 300 s, LRU of 4096 nonces; used on the device only
def parse_hello(body) -> DeviceHello; def parse_exec(body) -> WireExec; def parse_chunk(body) -> Chunk; def parse_result(body) -> tuple[Outcome, Chunk | None]   # the optional inline tail (A15.2, R2)
```

Wire bodies carry only what the other side uses:

- `hello` (device to relay, at pairing): `pubkey`, `name`, `os`, `arch`, `home`, `temp_dir`, `agent_version`. Signed with the key whose public half it carries, which proves possession.
- `exec` (relay to device, inside the poll response): `id`, `command`, `script`, `login`, `timeout_s`, `stdin`, `cwd`. No session key, no task id; the device has no use for them.
- `chunk` (device to relay): `id`, `seq`, `data` as base64 of raw bytes. The relay writes the bytes to the pipe; core decodes once.
- `result` (device to relay): `id`, `state` (`finished` or `refused`), `exit_code`, `duration_ms`, `truncated`, `reason`, and optionally `seq` plus `data`: the unsent tail of the output, at most `CHUNK_BYTES`, so a short command costs one post after the poll (A15.2, R2). The relay feeds the tail, then closes.
- The poll response body: `exec` (optional) and `cancel` (a list of request ids). A cancel is a field, not a message.

The gateway checks `ts` within 300 seconds and nothing more: a replayed chunk is dropped by `seq`, a replayed result by terminal state, a replayed hello by the single-use code. The device keeps the full `ReplayGuard`, because `exec` has no sequence number.

Order of operations in every device route, in this order and nowhere else: `registry.credential_for(bearer)` (401 if `None`) → `verify()` with that credential's key (400 on failure; a `Pending` credential is accepted only by the pair route, which verifies against the key inside the hello) → `relay.touch` for a `Device` credential only, so a stolen bearer without the signing key cannot keep a device online → `parse_<kind>()` → one relay or registry call → `410` when the relay reports terminal or unknown. The relay and everything below it never see a dict. Handlers never rely on `request.state.token_principal`, so the code path is the same with the dashboard gate on or off.

## A9. Device agent

`loop.py` runs one poll thread and at most `policy.max_parallel` executor threads through a `BoundedSemaphore`. The only state shared between them is `running: dict[RequestId, Popen]` under a lock, used by cancel and by shutdown.

```python
def serve(cfg: DeviceConfig) -> None:
    client = httpx.Client(base_url=cfg.gateway_url, headers={"Authorization": f"Bearer {cfg.token}"}, timeout=35)
    delay = 1.0
    while True:
        try:
            wire = client.post("/api/plugins/dirtside/device/poll", json=sign(cfg.key, "poll", cfg.device_id, {}))
            if wire.status_code == 401: kill_all(running); return log("revoked by the gateway; stopping")
            wire.raise_for_status(); delay = 1.0
            env = verify(cfg.relay_pubkey, wire.json(), now(), guard)
            for rid in env.body.get("cancel", []): kill(running.pop(rid, None))
            if "exec" in env.body: pool.spawn(handle_exec, parse_exec(env.body["exec"]))
        except (httpx.HTTPError, ProtocolError) as e:
            log(e); sleep(delay); delay = min(30.0, delay * 2)

def handle_exec(req: WireExec) -> None:
    outcome = executor.run(req, cfg.policy, send=lambda seq, data: post_until_2xx("chunk", {"id": req.id, "seq": seq, "data": b64(data)}))
    post_until_2xx("result", outcome_body(req.id, outcome))
```

`post_until_2xx` retries with the same backoff and stops on 2xx or 410. A 410 means the gateway already closed the request (cancelled, lost, or finished), so the device has nothing left to say.

`executor.run` evaluates policy first. A `Refused` becomes `Outcome(REFUSED, 126, ...)` without spawning. Otherwise it spawns `bash -l -c` or `bash -c`, `cwd=req.cwd`, `start_new_session=True`, writes the stdin payload from a separate thread and closes it (a child that fills the output pipe before it reads stdin would otherwise deadlock, which is why core has a writer thread too), reads stdout and stderr merged as bytes through `select`, flushes unsent output `FLUSH_MS` after its first byte, at `CHUNK_BYTES`, or at exit, whichever comes first (so a command that ends inside 200 ms makes one post), from the same thread and one post at a time (so `seq` arrives in order by construction), carries the final tail inside the result, stops reading about 300 ms after bash exits with the pipe idle (the same rule as core's drain in `tools/environments/base_output.py`, so a backgrounded grandchild such as `sleep 30 &` cannot hold the request open), enforces the backstop `min(req.timeout_s + 1, policy.max_timeout_s)` with SIGTERM then SIGKILL after 3 seconds, caps output at `policy.max_output_bytes` (default `MAX_OUTPUT_BYTES`) and reports `truncated`. Chunk retries share that capped duration. The gateway owns the requested timeout; the device's extra second lets core cancel first without exceeding device policy (A16.4). A 410 on a chunk or result for a running request kills that request's process group: the gateway no longer wants it. The group is killed only on timeout, cancel, revoke or 410, never after a natural exit: a grandchild such as `uvicorn &` or a `spawn_via_env` job must survive on the device exactly as it survives locally.

`policy.evaluate(command, policy)` is a pure function with one rule: no deny pattern matches the model's command. It returns `None` or `Refused(reason)`. The wrapped script is never inspected, because it contains the snapshot path, `/dev/null` and whatever the user's login shell references.

What the device enforces, stated plainly: the deny list, the timeout and output caps, the parallelism cap, and the kill switch. It does not confine where a command can dirtside. A folder allowlist cannot be enforced without a sandbox, and claiming one would be a false promise, so v1 does not have one.

## A10. Authentication

`DirtsideDeviceAuth(DashboardAuthProvider)`: `supports_token = True`, `interactive_login = False`, `supports_session = False`. `verify_token(token)` is a pure recogniser: it returns `TokenPrincipal(principal=name, provider="dirtside", scopes=("dirtside",))` when `registry.credential_for(token)` is not `None`, else `None`. It has no side effects, so the handlers' own bearer lookup is the single source of identity whether the gate is on or off. The session methods mirror the bundled drain provider line for line: `verify_session` returns `None` so the cookie loop passes over Dirtside, and `revoke_session` returns `None`. The four device routes are registered with `register_token_route()` at `register()` time.

Pairing under the gate works because the pairing code is itself a bearer the recogniser knows: `/dirtside pair macbook` creates a pending row whose `token_hash` is the code's hash, the device presents the code as its bearer on `/device/pair`, and `complete_pairing` rotates it to the long-lived token in one transaction. There is one credential type and one lookup path.

If plan open question 2 shows `register_token_route` is not usable by a community plugin, `auth.py` is deleted and the device presents `HERMES_DASHBOARD_SESSION_TOKEN` instead. Nothing else changes.

## A11. Routes

Device routes, fixed paths, bearer plus signed body: `POST /api/plugins/dirtside/device/pair`, `/device/poll`, `/device/chunk`, `/device/result`. Desktop routes, dashboard session: `GET /devices`, `GET|PUT /sessions/{key}/target`, `GET /requests`, `POST /pairing`, `POST /devices/{name}/revoke`. Every handler is under 15 lines.

There are no plugin events. The pane polls `GET /devices` and `GET /requests` every 2 seconds while visible and renders the difference. Online state comes from the gateway on every poll, so the pane never needs a previous state.

## A12. Slash commands, CLI, prompt section

`/dirtside`, `/dirtside use <name|server>`, `/dirtside devices`, `/dirtside pair <name>`, `/dirtside revoke <name>`. Handlers are `(raw_args: str) -> str` and resolve the conversation through `session_identity()`. `/dirtside use` with no argument calls `ctx.ask_choice` with the online devices plus `server`. `/dirtside revoke` calls `relay.revoke` so a running command on that device is cancelled immediately. Targets persist (`targets` table); live handles do not.

`hermes dirtside pair <gateway-url> --name <name> --code <code>`, `hermes dirtside serve`, `hermes dirtside status`, `hermes dirtside install-service` (launchd on macOS, `systemd --user` on Linux, both idempotent).

`current_target_section(session_info)` returns at most 600 characters naming the target, its OS and its home, or an empty string for `Server`. Registered as `ctx.register_system_prompt_section("dirtside.target", current_target_section, position="after_memory", max_chars=600)`. Core renders it once per new session and freezes it, so after `/dirtside use` mid-conversation the model learns the change from the command's reply text and the section catches up on the next session.

## A13. Invariants, each with the test that proves it

| Invariant | Test |
|---|---|
| A command never runs on the server when the conversation chose a device | `test_offline_fails_closed`: offline → `EnvironmentConnectionError`, `LocalEnvironment` never constructed |
| Cron never runs on a device by default | `test_resolve_target_table` |
| A request has exactly one terminal state and its pipe closes with it | `test_close_idempotent`: two threads close, one `True`, pipe EOF once |
| `kill()` unblocks a waiting tool thread at once | `test_kill_unblocks_wait` |
| A device that vanishes loses its queued and running requests within grace | `test_lost_covers_queued` |
| Chunks arrive in order; duplicates and late chunks are dropped; late posts get 410 | `test_feed_dedupe`, `test_late_result_410` |
| Revoke cancels that device's live requests and stops its polls | `test_revoke_cancels_running` |
| A pairing code works once, under the gate, and expires | `test_pairing_code_lifecycle` |
| Multibyte output survives chunk boundaries | `test_multibyte_chunks` |
| Approvals stay on and the environment survives a turn | `test_provider_flags`: `skip_container_guards is False`, `_persistent is True` |
| The deny list refuses what it says | `test_policy_table` |
| The whole path works without a second machine | `test_roundtrip_fake_device`: `create_environment(...).execute("pwd")` through `tools/fake_device.py`; `write_file` round trip byte-exact |
| A fast writer never loses bytes | `test_feed_never_drops`: three 64 KB chunks against a reader taking 4,096 bytes every 100 ms (core's shape); 196,608 bytes come out of the pipe and no feed exceeds `FEED_BLOCK_S` |
| A natural exit never kills a grandchild on the device | `test_grandchild_survives`: after `sleep 30 &` returns, the `sleep` is still alive on the device |
| A short result costs one post | `test_result_inline_tail`: `echo hi` through the fake device makes exactly one device post after the poll |
| Local and Dirtside agree | `test_conformance`: the A15.3 battery gives the same `output`, `returncode` and `cwd` through `LocalEnvironment` and through `DirtsideEnvironment` with the fake device |
| A backgrounded grandchild does not hold the tool | `test_grandchild_returns`: `sleep 30 &` returns in under one second on the device |
| Background jobs run through the relay | `test_spawn_via_env`: `process_registry.spawn_via_env` against the fake device; the log delta arrives and the exit code is recorded |
| The README numbers are reproducible | `tools/bench.py --loopback` in CI; it fails when an A15.1 target is missed |
| No file grows past its budget | `tools/check_sizes.py` in CI |

## A14. Build order, each unit ends in its check

1. Scaffold: repo, `pyproject.toml`, ruff, pytest, `tools/check_sizes.py`, CI, `plugin.yaml`, an empty `register()`. Check: `hermes plugins doctor . --ci` passes. Day-0 stubs answer plan open questions 1 to 4 and whether `HERMES_SESSION_KEY` is bound inside slash-command handlers and the prompt-section callable.
2. `model.py`, `protocol.py`. Check: envelope round trip, replay, wire bodies.
3. `registry.py`. Check: pairing lifecycle, revoke, `mark_stale_lost`.
4. `relay.py`, `environment.py`, `tools/fake_device.py`. Check: `test_roundtrip_fake_device`, `test_close_idempotent`, `test_kill_unblocks_wait`, `test_lost_covers_queued`, `test_feed_never_drops`, `test_conformance`. This is the day-1 gate.
5. `provider.py`, server target. Check: with `terminal.backend: dirtside` and no device, `pwd` runs on the gateway unchanged, and `cd` survives a turn.
6. `agent/*`, `cli.py serve`. Check: two processes on one machine run the plan's integration matrix.
7. `auth.py`, pairing route, `cli.py pair`. Check: a device pairs with a minted code with the gate on, a wrong code fails, a reused code fails.
8. `commands.py`, `prompt.py`. Check: `/dirtside use` from Telegram changes where `pwd` runs.
9. `desktop/plugin.js`. Check: pane shows a live request; chip shows the target.
10. `cli.py install-service`. Check: reboot the device, it comes back online.
11. Reliability matrix from the plan section 8, run by `scripts/two_machine_matrix.sh`, transcripts saved under `evidence/`. `tools/bench.py` over loopback, LAN and the two-machine rig; its output goes under `evidence/` and into the README with the commit SHA and the date.
12. README, disclosures, catalog YAML, `validate --install-deps` clean.

## A15. Execution strategy: fast where it is felt, exact everywhere

Two sentences define the goal, and every rule below serves one of them. A command on a device returns the same `output`, `returncode` and `cwd` that `LocalEnvironment` would return on that machine. The time Dirtside adds on top of the command itself is one network round trip plus a few milliseconds. Each rule carries the number that justifies it: measured on 2026-11-05 on an Apple silicon Mac under Python 3.15 with PyNaCl, or read from the core source named in the row. The gateway will run an older Python; the numbers are a scale, not a promise.

### A15.1 Where the time goes

The path of a short command such as `pwd`:

| Step | Who | Cost | Source |
|---|---|---|---|
| `execute()` wraps the command: source the snapshot, `cd`, run, emit the cwd marker | gateway, core | string formatting, not measured, well under a millisecond | `base_env.py` `_wrap_command` |
| `submit()` logs the request and notifies the parked poll | gateway, plugin | 0.02 ms per SQLite insert and commit at `synchronous=NORMAL` (0.2 ms at `FULL`) | measured |
| The exec rides the poll response | network | no extra round trip; the device's poll was already parked on the Condition | A5 |
| The device verifies the envelope and spawns the shell | device | verify 0.5 ms; `bash -c true` 6 ms; `bash -lc true` 16 ms on this Mac, and more on a profile that loads nvm or conda (not measured) | measured |
| Output and exit code travel back | network | one round trip when the tail fits in the result, two when a separate chunk was needed | A8 |
| The relay checks the signature, feeds the pipe, closes the handle | gateway, plugin | sign 2.2 ms and verify 1.6 ms for a 64 KB body, 0.2 and 0.5 ms for a small one; base64 0.03 ms; the pipe write under 0.1 ms | measured |
| Core notices the exit | gateway, core | `_wait_for_process` polls every 5 ms at first and backs off by 1.5x to a 200 ms cap after about 0.6 s | `base_env.py` |
| Core stops draining | gateway, core | at EOF, as soon as `close()` shuts the write end; the three 100 ms idle ticks apply only while a grandchild still holds the pipe | `base_output.py` `_drain_fd_select` |

The floor for `pwd` is therefore one round trip plus about 10 ms of work. The poll back-off is core's and the local backend pays it too, but it does not cancel out: the exit is noticed up to one poll interval late, 5 to 200 ms depending on how long the command ran, and that shows up in p95. `tools/bench.py` measures the same command through `LocalEnvironment` and through `DirtsideEnvironment` and reports the difference. The fake device signs and verifies exactly like a real one; otherwise the loopback column would measure nothing.

| Measure | Loopback, fake device | LAN | Internet |
|---|---|---|---|
| `pwd`, p50 added over local | at most 15 ms | at most 40 ms | at most one RTT plus 40 ms |
| `pwd`, p95 added over local | at most 40 ms | at most 100 ms | at most two RTT plus 100 ms |
| 10 MB of output (`head -c 10M /dev/urandom \| base64`) | at least 8 MB/s | at least 8 MB/s | uplink speed, up to 8 MB/s |
| `/stop` to tool return while a command runs on the device | at most 50 ms | at most 50 ms | at most 50 ms; the gateway closes first and the device learns on its next poll |
| Partial output present after a timeout or a cancel | everything written more than `FLUSH_MS` before the kill | same | same |

The throughput bound is CPU, not the link: one signature per chunk costs about 4 ms of signing and verification per 64 KiB (measured, R6), so a gigabit LAN at 125 MB/s cannot be reached by this protocol shape. A15.4 names the lever if a measured transfer ever needs it.

Precedent for the transport, since the choice is the main thing a reviewer will question: GitHub's self-hosted runner receives jobs over an outbound HTTPS long poll held for 50 seconds ([GitHub docs](https://docs.github.com/en/enterprise-server@latest/actions/hosting-your-own-runners/about-self-hosted-runners)), the remote-control feature of a major coding assistant registers its local process over an outbound connection and polls a relay, and VS Code Remote Tunnels keep a persistent outbound connection to a tunnel service ([VS Code docs](https://code.visualstudio.com/docs/remote/tunnels)). One measured comparison puts the per-message latency difference between long polling and WebSockets under 0.3 ms at low event rates on a reused connection; the gap only opens when events arrive faster than one round trip, which a shell command cannot do ([comparison](https://daily.dev/posts/websocket-vs-sse-vs-long-polling-the-real-cost-of-1-000-events-wip1lzawd)). Cloudflare's tunnel daemon opens four outbound connections for availability, not for speed ([Cloudflare docs](https://developers.cloudflare.com/tunnel/configuration)); one device, one connection is enough here.

### A15.2 Rules

- **R1. Dispatch costs no round trip.** The device's poll is parked on the relay Condition; `submit()` notifies and the exec rides the poll response. The device re-polls at once after every response, so a request only ever waits in `QUEUED` for the one round trip of a poll in flight. The agent keeps one `httpx.Client` for its lifetime, so TLS is negotiated once per connection, not per request.
- **R2. Short results travel in one post.** When the unsent tail of the output is at most `CHUNK_BYTES`, the device puts it inside the `result` instead of a separate chunk. `pwd`, `ls`, `git status` and a test summary cost one upload. The relay feeds the tail and then closes, under the same single terminal transition.
- **R3. Flush on a clock, finish in the result.** The executor flushes unsent output `FLUSH_MS` after its first byte, at `CHUNK_BYTES`, or at exit, whichever comes first, and the final tail rides in the result. A command that ends inside 200 ms costs one post (R2); a long one shows output on the pane within 200 ms (R8); and a timeout or a cancel loses at most the last 200 ms of output, which is what core's `[Command timed out after Ns]` rendering shows the model.
- **R4. The feed is lossless and backpressured.** A 64 KB chunk is exactly one pipe buffer on macOS (measured), so a second chunk that lands before core's drain thread is scheduled cannot fit, and a non-blocking writer that ignores the short count drops the remainder: the first draft had that bug. `feed()` now writes every byte, looping on `select` for writability in one second slices on the relay's own pool, bounded by `FEED_BLOCK_S` in total and re-checking terminal state each slice (A5). Because the device posts one chunk at a time and waits for the 2xx, a slow reader slows the device and nothing is dropped. The bound is the only exit: past it the request closes as `LOST` with reason `gateway stopped reading output`, the device gets 410 on its next post and kills the process group.
- **R5. The login shell runs once.** Core's `init_session()` runs the login bootstrap once per environment and later commands run `bash -c` sourcing the snapshot (6 ms against 16 ms here, and far more on heavy profiles). `_persistent = True` keeps that environment across turns. The device runs exactly the `login` flag it is given and never upgrades a command to a login shell on its own.
- **R6. Nothing on the hot path waits on disk or on a lock.** The registry is written at `submit()` and `close()` only, at `synchronous=NORMAL` (0.02 ms; the request log is the only thing at risk on power loss, and it is a log). Chunks never touch SQLite. The Condition is held for microseconds; the pipe write and the signature check happen outside it. Signing costs 2.2 ms and verifying 1.6 ms per 64 KiB chunk (an 87 KB body after base64), so the device signs about 29 MB/s and the relay verifies about 42 MB/s on one core; in series, with one post per chunk, that bounds a transfer near 10 to 16 MB/s, below a gigabit LAN and above most home uplinks. Small messages cost 0.2 to 0.5 ms.
- **R7. Background jobs are left to core.** `process_registry.spawn_via_env` wraps the command as `nohup bash -lc` with a log, a pid file and an exit file under `get_temp_dir()`, then polls with two `execute()` calls every 2 seconds (a log delta and a `kill -0`) and one more to read the exit file at the end. Each poll is one normal request through the relay. Two consequences to know: every background job pays the login shell once (the wrapper's `bash -lc`, outside R5), and the wrapper's `( ... ) &` subshell holds the output pipe, which is exactly the case R10 exists for; without R10 the spawn call (default `timeout=10`) would time out and a group kill would take the job with it. Dirtside adds nothing here; the conformance test proves the path works.
- **R8. Progress is visible where the user is looking.** The relay keeps the last `PANE_TAIL_BYTES` of each live request in memory and `GET /requests` returns it, so the Desktop pane shows output as it streams while the phone waits for the tool to return. Core only shows a foreground command's output when it ends; the pane is the surface that makes a 40-second test run feel alive. A ring of bytes, no new route, no event.
- **R9. Core's limits are the only truncation the model sees.** Core keeps a 40/60 head and tail window at `tool_output.max_bytes` (50,000 by default) and spills up to 5 million characters to disk for recovery, so the foreground path discards everything past about 5 MB anyway. The device still ships everything up to `MAX_OUTPUT_BYTES`, because the internal paths run with full fidelity: `read_file` is a `cat` through `execute()` with `bounded_capture=False`, and truncating it would corrupt a file read. When the device does hit its cap it reports `truncated`, and the environment appends one line, `[Dirtside: output capped at 64 MB on the device]`, so the notice is honest.
- **R10. The device drains like core.** The executor reads through `select` and stops about 300 ms after bash exits with the pipe idle, and it never kills the process group after a natural exit (A9). Without the first half `sleep 30 &` would hold the request for 30 seconds on the device while it returns at once locally; without the second half the backgrounded `sleep`, a `uvicorn &` and every `spawn_via_env` job would die on the device while they survive locally. Both are conformance failures, not performance ones.

### A15.3 Accuracy: the conformance battery

The test that others will not write. Every case runs through `LocalEnvironment` and through `DirtsideEnvironment` with `tools/fake_device.py` in the same process, and the two results must be equal in `output`, `returncode` and the environment's `cwd` afterwards.

| Case | What it pins |
|---|---|
| `pwd` | the home translation and the cwd marker |
| `cd /tmp` then `pwd` in a second call | cwd persistence across calls |
| `export X=1` then `echo $X` in a second call | the snapshot round trip |
| `exit 3`, `nosuchcommand` | exit codes 3 and 127 |
| `echo a; echo b >&2; echo c` | merged stream order |
| `printf` of three-byte characters across the 64 KB boundary | multibyte decoding once, on the gateway |
| `head -c 100000 /dev/urandom \| base64` | binary-safe chunks |
| 1 MB of `seq` | many chunks, in order, no loss |
| `sleep 5` with `timeout=1` | exit 124, partial output, the device process gone |
| `write_file` of 1 MB then `read_file` | the stdin payload path, byte-exact |
| `patch_replace`, `search_files` | the file tools' shell commands |
| `cd` into a missing directory | the wrapper's exit 126 message |
| `sleep 30 &` | the drain rule, returns in under a second |
| `process_registry.spawn_via_env` then two polls | background spawn, delta, exit code |
| `/stop` during `sleep 60` | exit 130 at once; the device process is dead within 5 seconds |
| device agent killed with SIGKILL mid-command | `LOST` within `OFFLINE_AFTER_S + LOST_GRACE_S`, exit 124, partial output kept |
| a chunk post that fails once and retries | the same `seq` is accepted once; no doubled bytes |
| gateway restarted mid-command | the device's next post gets 410 and it kills the process; its next poll succeeds without re-pairing |

### A15.4 Deferred, each with the trigger that reopens it

- **Chunk compression.** `zlib` level 1 costs 0.2 ms per 64 KB and shrinks `ls` output six times, random bytes not at all. Add an `enc` field when `tools/bench.py` over a real uplink shows upload time dominating a test-suite run.
- **A heartbeat during a running command.** Loss is detected within 50 seconds (`OFFLINE_AFTER_S` 45 plus `LOST_GRACE_S` 5). Add a 5 second heartbeat post while a request runs when a user reports waiting too long after pulling a laptop's cable.
- **HTTP/2 or WebSocket.** Only if a gateway in front of a proxy cannot hold a 25 second poll; then shorten `POLL_HOLD_S` first.
- **Throughput above 8 MB/s.** The per-chunk signature is the bound (R6). The lever is to sign a running SHA-256 over the stream and verify once at the result, so chunks carry a hash chain instead of a signature, or to pipeline posts with a window of two. Add when `tools/bench.py` shows a real transfer waiting on CPU.
- **A pre-warmed shell per session on the device.** Saves the 6 ms spawn per command. Not worth a second process model.

## A16. Day-1 gate: what was built and what changed

Built on 2026-11-05 by the builder from A14 steps 1 to 5 plus `agent/policy.py` and `agent/executor.py`, through the OpenSpec change `dirtside-day1-gate`. On the owner's own run: 121 tests, ruff, the size budgets, `openspec validate --strict` and `hermes plugins doctor --ci` all pass against core main at 84a0301 (Python 3.14.6, macOS). Nothing is committed yet.

Deviations the builder found in the source and that are now part of the design:

- `executor.run(req, policy, send, *, cancel) -> tuple[Outcome, Chunk | None]`: the final tail is returned to the caller, which puts it inside the result, and cancel is a `threading.Event` the loop sets. A9's sketch had no channel for either.
- The model's raw command travels in a `ContextVar` set by `execute()`, not an attribute on the environment. Core's deadline worker copies context, and an attribute would let concurrent calls apply policy to the wrong command (A6).
- A root `__init__.py` that lazily imports `dirtside.register` is required by directory discovery. `dirtside/__init__.py` stays the package entry point.
- An empty session identity never reads a target row (A7), so an unbound caller cannot borrow a device choice.
- `bash` is resolved through PATH on the device, so missing-command and missing-directory diagnostics match core's local backend byte for byte.
- The truncation notice names the configured cap, not a constant.
- Core forwards `stdin_data` directly for `_stdin_mode = "payload"` (`base.py:727`); there is no separate branch to mirror.
- `requires_hermes` is `>=0.22.7`: that release (2026-11-03) carries the payload mode (`base.py:272`), the `_persistent` check (`terminal_tool_lifecycle.py:270`), `register_token_route` (`token_auth.py:31`) and the provider ABC, at the same lines as main.

Open for the next steps, with the section each one changes:

- Target representation (A4, A7, step 8), resolved in A16.3: a `targets.device_id` column cannot express an explicit `server` choice over a non-server default. The implemented `target TEXT` stores `server` or a device id; no row means the default.
- CI (A14 step 1) runs on GitHub-hosted runners: clone core at the pinned SHA, `uv sync`, then the five checks. The first draft assumed a prepared checkout on a self-hosted runner.
- Device stop waits up to 3 seconds for exit after SIGTERM instead of sleeping 3 seconds, so a cancel is as fast as the process allows.
- Parallel calls on one environment share core's snapshot file, as they do on the ssh backend. Not serialized; noted, not fixed.
- A device output cap can cut the cwd marker. The environment keeps the previous cwd and the notice says so.

### A16.1 Day-2 network path

Built the same evening from A14 steps 6 and 7 plus every route in A11, through the OpenSpec change `dirtside-day2-network`; 169 tests, the five checks and the name scan pass on the owner's run against the same core SHA. What the source forced or the builder chose:

- The dashboard router module is loaded in its own namespace, so it reaches the registry and relay through the registered auth provider: `hermes_cli.dashboard_auth.get_provider("dirtside")` returns the `DirtsideDeviceAuth` instance, which carries both. That adds `hermes_cli.dashboard_auth.get_provider` and `hermes_constants.get_hermes_home` to the allowed imports in A3.
- The chunk and result routes check that the request belongs to the posting device (`relay.accept_chunk`, `relay.accept_result`) before feeding or closing, so one device cannot finish another device's request.
- `complete_pairing` binds the exact code that was presented, so a reminted code for the same name cannot be consumed by an older device.
- The relay gained read accessors for the pane: `device_status()` (device, online, last seen) and `recent()` (registry rows with live state and the output tail).
- The device keeps a private rotating log of events (`agent/activity.py`, mode 0600, no commands, output or credentials); `hermes dirtside status` reads it instead of polling, so status can never claim work.
- `DeviceConfig` accepts HTTPS, or HTTP on loopback only; pairing pins the relay public key; the default deny list covers privilege escalation, recursive deletion of the root, filesystem formatting, raw disk writes, shutdown and reboot, service stops, fork bombs and piping a download into a shell (the exact patterns are in `agent/config.py`).
- Workers in the loop track cancel Events, not processes; the executor owns the process groups. A 410 during execution cancels that request; a 410 after a natural exit cannot kill a surviving background job, which keeps R10.
- Python's default executor here is `min(32, cpu_count + 4)` (14 on this Mac), so the router owns its own 16-thread pool for polls and feeds, as A5 requires.
- Integration point originally left open: `PUT /sessions/{key}/target` used `set_target(key, None)` for `server`. A16.3 resolves this with the stored sentinel and non-server-default route tests.

### A16.2 Day-3 inside the real core

Built the same night from the A14 step 5 and 6 checks, step 10 and the step 11 script, through the OpenSpec change `dirtside-day3-integration`; 193 tests and the loopback reliability matrix (8 of 8 rows) pass on the owner's run. The tests load the plugin through core's own loader into an isolated home, drive core's `terminal` and file tool entry points against a paired agent subprocess, and mount the router through core's dashboard discovery with the auth gate on. Two defects that only the real core could show, both fixed:

- **Cached environments skipped the offline check.** Core reuses an environment without calling the provider again, so the creation-time check in `resolve_target` did not protect the next command after an outage; the model got a generic timeout. `environment.require_online` now runs before every dispatch in `_run_bash` and reports the offline device with "Nothing was run on the server" (A6, A7).
- **An abandoned long poll could claim work.** When an agent restarted, its old handler stayed blocked in `relay.next` and consumed the next queued request after the connection was gone, while the new agent kept heartbeating. The poll route now watches the ASGI receive channel and passes a cancelled Event into `relay.next`, which wakes every 100 ms while a watcher exists (A5, A11).

Core behaviors to know, none patched around: an explicit `terminal.cwd: "~"` is expanded on the gateway before the provider runs, so the config leaves it unset and the device home applies; file reads through a remote backend are recorded as partial by core (`file_tools.py` takes a version baseline only for host paths), so a remote patch result carries a pagination warning that the local backend does not; the displayed terminal result strips trailing whitespace and bounds large output while the recovery file keeps the shell trailers; concurrent calls with different child task ids share one `session:<key>` environment; a URL-safe pairing code can start with `-`, so the CLI documents `--code=<value>`; the plugin doctor refuses a `TMPDIR` inside the tree it validates. `install-service` renders launchd and systemd user units with pinned paths and private logs, with `--dry-run` and `--remove`; real loading was not exercised. The matrix is a 15-line bash entry over `tools/run_matrix.py`, because signed requests and owned fault injection need Python; evidence transcripts are written under `evidence/` and kept out of git because they carry local paths.

### A16.3 Day-4 user surfaces

The active `dirtside-day4-surfaces` change implements A14 steps 8 and 9 and the A15.1 signed-loopback benchmark against the same pinned core. These amendments supersede the earlier API sketches:

- Targets migrate transactionally to `target TEXT NOT NULL` without a device foreign key, preserving selections and timestamps. `set_target(key, target: str | None)` persists literal `server` or a paired device id; `None` deletes the row. `target(key) -> str | None` replaces the old reader. Both route callers preserve their JSON shapes.
- Core caches environments, so changing the row alone cannot redirect the next command. The provider now returns `ConversationEnvironment`, which resolves on dispatch and keeps per-target delegates and shell snapshots. It disables the host-filesystem shortcut so cached file operations also follow the target. Removed and offline explicit targets fail closed.
- Core's recorded conversation cwd still crosses targets; the execution boundary does not distinguish it from explicit `workdir`. No heuristic translation is added. A path absent on the new target needs an explicit valid workdir.
- The bound text command, online-device picker and bounded quoted target facts use the existing registration contracts. Core freezes the prompt once; changing targets does not invalidate it.
- Native Desktop discovers `desktop/plugin.js` without another manifest. The opt-in pane uses SDK REST and React Query, stops device/request polling while hidden, and scopes reads and writes by connection, profile, activation and focused durable session key. A foreign or missing owner cannot write through the active gateway.
- The benchmark compares 50 paired commands, verifies all 10,000,000 output bytes and measures early running-command cancellation to tool return. It exposed a fixed 100 ms EOF-before-exit delay in the device executor, replaced by a bounded 10 ms process wait. No core code changes. HTTP and late cancellation are not certified by that measurement; core's adaptive polling can delay the latter by up to 200 ms.
- README contains installation, four-command pairing, security disclosures and dated measurements. The private day-4 report records acceptance outputs and limits. Desktop runtime, physical two-host and real service-manager checks remain unperformed.

### A16.4 Day-5 Linux portability

The active `dirtside-day5-linux` change fixes deadline ownership and test assumptions against the same pinned core. Linux validation remains the owner's GitHub-hosted run.

- Execution and chunk retries use the same pure `device_timeout_s` calculation: the requested timeout plus one second, still capped by device policy. Cancellation does not wait for the backstop.
- A wait-only handle view holds an explicit finished device timeout for core's own deadline branch. Core supplies the exact suffix, exit 124, `hermes_timed_out`, bounded capture and spill metadata. Raw handle completion remains unchanged. An earlier device-policy stop can wait the remaining caller budget for rendering, but cannot keep executing.
- A combined timeout and output cap retains the timeout reason first and the cap notice after `; `. The environment renders the cap notice separately. Ordinary exit 124, loss, refusal and cancellation remain distinct.
- Signal tests keep bash and a child alive with a compound command. Pool coverage uses acknowledged dispatch and whichever workers actually start, with ten-second readiness deadlines and the existing five-second cessation bounds. Cwd tests use quoted fixture paths; flush-clock boundaries and partial-output readiness do not depend on fixed sleeps.

---

# Part B. Explanation

## B1. Why a global backend with per-conversation targets

Core freezes `TERMINAL_ENV` into each session's policy in `gateway/session_policy.py` and binds it per turn through `policy_scope()`. That is gateway-internal; a plugin cannot set a different backend per session. So Dirtside is the backend for every session and its cached conversation adapter decides the target at dispatch (A16.3). The cost is that server-target sessions carry Dirtside's provider flags (`is_remote = True`), so their prompt loses the host OS hints. The alternative, switching `terminal.backend` by hand per conversation, defeats the product. The right long-term fix is an upstream seam, which the catalog README invites as an issue.

## B2. Why inherit `BaseEnvironment` instead of writing an executor

`BaseEnvironment.execute()` already does the snapshot sourcing that makes `cd` and `export` persist, the cwd markers, the interrupt handling, the wall-clock backstop, the bounded output capture and the sudo and macOS `open` rewrites. The SSH backend gets all of that from a 300-line subclass whose job is to spawn one local process. Dirtside's subclass is smaller, because it spawns nothing locally. An executor of our own would duplicate roughly 800 lines of core behaviour and drift from it with every release.

## B3. Why the handle is a pipe and not a callback

`_wait_for_process` drains `handle.stdout` on its own thread and fires activity callbacks as bytes arrive. Feeding raw bytes into a pipe gives partial output on timeout, liveness for long commands, one decode in core, and interrupt handling with no Dirtside code involved. A callback design would need Dirtside to reimplement all of that. The Modal and Daytona built-ins use the same pipe shape.

## B4. Why the relay owns live state and the registry is a log

The first draft kept request state in SQLite behind a compare-and-set and ran a sweeper thread. The review found the hole: cancel moved the state but nobody closed the pipe, so every timed-out command would have hung its tool thread. The gateway is one process, so one lock is a stronger arbiter than a database row, and it can close the pipe inside the same critical section. The registry now records what happened for the pane and for audit; it never decides anything. The sweeper went with it, because the thread already waiting on a handle can notice the device is gone.

## B5. Why threads and one Condition, with a dedicated pool for polls

Tool calls run on Hermes worker threads and must block until the device answers. Route handlers run on the gateway's event loop and must not block. One mechanism, threads and a `Condition`, keeps the domain code free of "am I on the loop?" questions. The poll route gets its own executor because `asyncio.to_thread` shares the loop's default pool with the rest of the gateway, and eight devices holding 25-second polls would starve chat on a four-core box.

## B6. Why online and lost are derived, and the heartbeat is the poll

A stored flag lies after a crash and needs a second writer. A `last_seen` timestamp compared against a window cannot lie, costs nothing, and makes "lost" the same computation per request. The poll held for 25 seconds and returning empty is the heartbeat, so there is no heartbeat message.

## B7. Why a refusal is a result and a cancel is a field

A refusal is a terminal outcome with a reason, which is what a result already is. Folding it in removes a route, a parser and a transition. A cancel rides the poll response because that channel already exists and needs no acknowledgement: the device's later result for that id is answered with 410.

## B8. Why the pairing code is a pending device

The first draft had a `pairing_codes` table and a second credential kind. Under the dashboard gate, the middleware rejects any bearer no provider recognises before the handler runs, so a code the recogniser did not know could never dirtside the pairing route. Making the code the pending device's own short-lived bearer gives one credential type, one lookup, one table, and pairing that works with the gate on.

## B9. Why the device has a deny list and no folder allowlist

The first draft scanned the script for absolute paths and refused anything outside allowed directories. The script that reaches the device is the wrapped one, which references the snapshot file in the temp directory and the user's login shell, so the default policy would have refused every command on both platforms. And a token scan is not a boundary: relative paths, `cd`, symlinks and `$HOME/..` all walk past it. Only a sandbox confines a command. Rather than ship a guard that looks like one, v1 enforces what a device can enforce (deny patterns on the model's own command, caps, the kill switch) and says so.

## B10. Why there are no model tools and no device-side prompts

The thread that produced this design was explicit that the model must never choose where a command runs. A device-listing tool would be an invitation to do exactly that through prompt injection. The model learns the target from a prompt section. Hermes already asks the user in chat before a dangerous command and the provider keeps that on, so a second prompt on the device would add a third actor, a timeout policy and a UI on a machine that may have no screen. It stays on the stretch list.

## B11. Why the lints exist

Every "keep files small" and "no scattered conditionals" instruction gets ignored under deadline pressure. `tools/check_sizes.py` and `mccabe.max-complexity = 8` fail CI instead. `TERMINAL`, `Credential`, `Target` and `Decision` are the same idea in type form: the next case is a variant, not a branch.

## B12. What the review cut from the first draft

- The SQLite compare-and-set, the `TRANSITIONS` table and the sweeper thread (B4).
- The `pairing_codes` table, `relay_key` table and the second credential kind (B8).
- The folder allowlist and the path-token scan (B9).
- Eight plugin events, their broadcasts and the pane's subscriptions. The pane polls.
- The settings page. `config_schema` renders the form.
- The `on_session_end` hook. It fires per turn with a session id the relay does not index, and core already calls `cleanup()` on idle reap and session close.
- A `Settings` dataclass and three knobs that were constants. `default_target` is the one setting.
- `session_key` and `task_id` on the wire, `token_hash` on the `Device` type, `script_sha256` and `bytes_out` columns, the poll offset field, a `Backoff` class, `hermes dirtside demo`, the gateway-side replay LRU, and the explicit `skip_container_guards` override (the ABC derives it from `is_container`; the test pins the value).

## B13. What a reviewer should push back on first

Three facts settle on day 0 before any module above is written: whether `register_token_route` is usable from a community plugin (A10 fallback), what cwd reaches `create_environment` with `is_container = False` when `terminal.cwd` is set or Desktop opens a project folder (plan open question 4), and whether `HERMES_SESSION_KEY` is bound inside slash-command handlers and the prompt-section callable, so `session_identity()` returns the same key everywhere. The fourth is the shared-snapshot note: two `execute()` calls on one environment share one snapshot file on the device, as they do on SSH; core serialises environment creation per task, not execution.

## B14. Why the speed work is in the protocol shape, not in the language

Everything Python does on the request path adds up to under 5 ms per small message: the SQLite write, the signature, the JSON, the pipe. A round trip on the internet is 20 to 100 ms, a shell spawn is 6 ms, and core's drain tail is 300 ms whenever a grandchild holds the pipe. Rewriting the plugin in Go or C would remove the few milliseconds and keep the rest, and would cost a second implementation of the protocol and a binary per platform. The rules in A15 remove whole round trips (R1, R2), remove a data loss (R4), keep grandchildren alive (R10), and make the slow parts visible (R8); that is where the time was. The one place CPU does bound the design is bulk output, at about 10 to 16 MB/s per device (R6), and the fix there is a protocol change, not a language change (A15.4). The conformance battery is the other half of the argument: speed that changes an exit code or drops a byte is a bug with a good benchmark.
