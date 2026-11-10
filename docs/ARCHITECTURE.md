# Dirtside architecture

Reference for Dirtside. Written 2026-11-05 against the contracts verified in `DIRTSIDE-PLAN.md` section 17, then revised against the implementation through the catalog review. The plan says what and when. Part A describes ownership and contracts; its original API sketches are historical where A16's implementation amendments supersede them. A3 records the enforced budgets. Part B explains the choices and alternatives.

Two rules govern every choice below. Build the smallest thing that does the job, on top of what Hermes already provides. Put the domain in data structures, so the code has few branches and no scattered modes.

---

# Part A. Reference

## A1. Languages and stack

| Layer | Language and runtime | Why this and nothing else |
|---|---|---|
| Gateway plugin (provider, relay, registry, commands, auth) | Python, the interpreter Hermes runs on (3.11 assumed, confirm against Hermes' `pyproject.toml` on day 0) | plugins load in-process; no choice |
| Device agent (`dirtside-agent serve` or `hermes dirtside serve`) | Python 3.11+, the same package, with or without Hermes | one codebase, one protocol module, nothing to drift |
| Relay HTTP routes | FastAPI `APIRouter` in `dashboard/plugin_api.py` | the only route surface Hermes mounts for plugins |
| Desktop half | JavaScript ES module, React through `jsx()` from `react/jsx-runtime`, `@hermes/plugin-sdk` | the loader takes uncompiled ESM only |
| Storage | one SQLite file under `plugin_data_dir("dirtside")`, WAL | survives `hermes plugins update`; no ORM |
| Signatures | Ed25519 through PyNaCl, pinned `pynacl>=1.5,<2` | bounded dependency; upper bound per catalog rule 10 |
| HTTP client on the device | `httpx>=0.28.1,<0.29`, declared for standalone installs | compatible with all three checked core revisions |
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
    os: str; arch: str; home: str; temp_dir: str; agent_version: str; owner: str = "local"

@dataclass(frozen=True)
class Pending:                             # a minted pairing code, until the device completes pairing
    name: str; expires_at: int
@dataclass(frozen=True)
class Revoked:                             # retained paired key, never active authority
    id: DeviceId; name: str; pubkey: bytes; revoked_at: int
Credential = Pending | Device | Revoked     # retained lookup: signed transport and token recognizer

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
    login: bool; timeout_s: int; stdin: str | None; cwd: str; sender: str = "local"

@dataclass(frozen=True)
class Outcome:                             # a terminal report, from the device or from the relay itself
    state: RequestState; exit_code: int; duration_ms: int; truncated: bool; reason: str

@dataclass(frozen=True)
class Policy:                              # parsed once on the device at its config boundary
    deny_patterns: tuple[re.Pattern, ...]; max_timeout_s: int; max_output_bytes: int; max_parallel: int
    env_passthrough: tuple[str, ...] = ()

@dataclass(frozen=True)
class Refused:
    reason: str
Decision = None | Refused                  # None means allowed

OFFLINE_AFTER_S = 45; LOST_GRACE_S = 5; POLL_HOLD_S = 25; PAIR_TTL_S = 600
CHUNK_BYTES = 65536; PART_MAX = 2 << 20; FLUSH_MS = 200; FEED_BLOCK_S = 10; PANE_TAIL_BYTES = 4096; MAX_OUTPUT_BYTES = 64 << 20
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
| `dirtside/backend.py` | explicit terminal-workdir context and lazy local handoff | stdlib, transitional core local environment | 22 |
| `dirtside/access.py` | sender identity, command-source provenance, visibility, owner authorization and shared configuration warning | public session context, environment error, lazy public config reader and prompt.quoted | 112 |
| `dirtside/model.py` | the types and constants above | stdlib | 118 |
| `dirtside/protocol.py` | `Envelope`, canonical JSON, `sign`, `verify`, `ReplayGuard`, one `parse_*` per message kind, `PROTOCOL_VERSION = 1` | model, nacl | 147 |
| `dirtside/readiness.py` | bounded pipe readiness without a descriptor-number ceiling | stdlib selectors | 8 |
| `dirtside/registry.py` | the SQLite boundary, retained credentials, relay key and private local secret | model, sqlite3 | 225 |
| `dirtside/relay.py` | one owner's live state, bounded pending local streams and the worker transport seam | model, registry, environment (handle), readiness, threading | 239 |
| `dirtside/environment.py` | `DirtsideEnvironment(BaseEnvironment)`, `RemoteProcessHandle`, dispatch through the relay's selected connection | model, `tools.environments.base` | 124 |
| `dirtside/client.py` | process-verified owner discovery, bounded disabled-route retry, local execution, stream-to-pipe copy, cancellation and live state reads | model, environment (handle and error), httpx, system ps | 198 |
| `dirtside/local.py` | bounded loopback request parsing, fixed local routes and raw output framing | model, protocol, relay, registry, readiness, FastAPI, anyio | 152 |
| `dirtside/provider.py` | dispatch-time conversation context, bounded cwd history and per-target snapshot delegates, `resolve_target()` | relay, registry, `agent.terminal_env_provider`, backend, environment, `gateway.session_context` | 183 |
| `dirtside/auth.py` | device and local-secret recognition, ten-second revoke window and exact route registration | registry, local, client (process identity), `hermes_cli.dashboard_auth` | 96 |
| `dirtside/shortcuts.py` | /land and /orbit adapters over Commands | commands | 20 |
| `dirtside/commands.py` | `/dirtside` handlers, text in and text out | relay, registry, provider (`session_identity`, `resolve_target`, session context) | 103 |
| `dirtside/awareness.py` | per-turn bounded target facts, server fallback or configuration warning, no liveness probe | prompt, provider, shared Access | 35 |
| `dirtside/prompt.py` | authorized frozen target facts or shared configuration warning | registry, provider (`session_identity`), shared Access | 38 |
| `dirtside/agent/platform.py` | Termux detection and measured system environment names | stdlib | 24 |
| `dirtside/agent/home.py` | override, legacy profile and standalone state lookup; service state environment | stdlib, optional public home helper | 22 |
| `dirtside/agent/console.py` | standalone console entry point | cli | 13 |
| `dirtside/cli.py` | shared standalone/Hermes device commands, service installation, re-pair recovery, bounded private refusal details and public-host hint | agent/*, argparse, httpx | 194 |
| `dirtside/agent/config.py` | `DeviceConfig` read and atomic write (`device.json`, 0600) | model, protocol | 100 |
| `dirtside/agent/policy.py` | `evaluate(command, policy) -> Decision`, pure | model | 40 |
| `dirtside/agent/executor.py` | `run(request, policy, send) -> Outcome`, process groups, chunking, cancel | model, readiness, subprocess | 115 |
| `dirtside/agent/loop.py` | poll, backoff, dispatch, bounded parallelism, retrying posts | config, policy, executor, protocol, httpx | 150 |
| `dashboard/plugin_api.py` | device-traffic owner publication, signed device routes, authenticated revocation, pane forwarding and local route mounting | auth's protocol, relay, registry and local route instance | 227 |
| `desktop/plugin.js` | pane, chip | `@hermes/plugin-sdk` | 280 |
| `__init__.py` | lazy directory entry point | package registration | 50 |
| `dirtside/__init__.py` | `register(ctx)` wiring | gateway modules | 58 |
| `tests/bench.py` | in-process metrics and non-gating client latency rows; existing thresholds remain, with report-only in CI | bench_client, statistics | 92 |
| `tools/fake_device.py` | a signed fake device, including the independently loaded core owner's result parser | agent/executor, relay | 82 |
| `tools/termux_forward.py` | owner-run container loopback bridge over stdio | stdlib | 62 |
| `tools/termux_check.py` | owner-run signed Termux lifecycle check and cleanup | core_rig, httpx, stdlib | 157 |
| `tools/check_sizes.py` | the size check | stdlib | 30 |

Production core imports, in full: `agent.terminal_env_provider.TerminalEnvironmentProvider` (provider), `tools.environments.base.BaseEnvironment` (environment), `tools.environments.base.EnvironmentConnectionError` (environment), `tools.environments.local.LocalEnvironment` (lazy backend handoff), `gateway.session_context.get_session_env` (access and provider), `plugins.plugin_storage.plugin_data_dir` (package registration), `hermes_cli.dashboard_auth.DashboardAuthProvider` and `hermes_cli.dashboard_auth.TokenPrincipal` (auth), `hermes_cli.dashboard_auth.get_provider` (registration and dashboard routes), `hermes_cli.dashboard_auth.token_auth.register_token_route` (auth), `hermes_cli.config.read_raw_config_readonly` (lazy gateway configuration warning), and `hermes_constants.get_hermes_home` (lazy optional device home lookup and legacy service installation). No production code monkeypatches Hermes. The separate test rig imports core's entry points to exercise them.

## A4. Registry (the SQLite boundary, and only a log for requests)

`Registry(path)` opens one connection per thread (thread-local), WAL, `busy_timeout = 5000`. The shared connection from `plugin_db()` is never used. Every public method is one transaction and returns a model type or `None`, never a row.

```sql
CREATE TABLE devices (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash BLOB NOT NULL,
  pubkey BLOB, os TEXT, arch TEXT, home TEXT, temp_dir TEXT, agent_version TEXT,
  created_at INTEGER NOT NULL, expires_at INTEGER, revoked_at INTEGER,
  owner TEXT NOT NULL DEFAULT 'local'
);                                   -- pubkey NULL and expires_at set = pending; pubkey set and expires_at NULL = paired
CREATE UNIQUE INDEX devices_active_name ON devices(name) WHERE revoked_at IS NULL AND pubkey IS NOT NULL;
CREATE TABLE retired_credentials (
  token_hash BLOB PRIMARY KEY, id TEXT NOT NULL, name TEXT NOT NULL,
  pubkey BLOB NOT NULL, revoked_at INTEGER NOT NULL
);
CREATE TABLE targets (session_key TEXT PRIMARY KEY, target TEXT NOT NULL, set_at INTEGER NOT NULL);
CREATE TABLE session_defaults (session_key TEXT PRIMARY KEY, target TEXT NOT NULL);
CREATE TABLE requests (
  id TEXT PRIMARY KEY, device_id TEXT NOT NULL, session_key TEXT NOT NULL, task_id TEXT NOT NULL,
  state TEXT NOT NULL, preview TEXT NOT NULL, created_at INTEGER NOT NULL,
  finished_at INTEGER, exit_code INTEGER, reason TEXT
);
```

The relay's Ed25519 seed is a 0600 file next to the database, `relay.key`, the same shape as `device.json` on the device.

An idempotent transaction adds `owner` to old device rows with default `local`, preserves existing devices, tokens, targets and requests, and records the minting sender on pending rows so completion and re-pairing keep that authority.

Revoked paired rows retain their keys and hashed tokens. Before same-owner re-pairing overwrites a paired row, the transaction copies its old key, token hash and identity into `retired_credentials`. `COALESCE(revoked_at, ?)` preserves its first revoke time or stamps the replacement time if still active. Pairing an already revoked name never starts a new window for the old credential. The replacement keeps the conversation's id, while the old credential resolves only to `Revoked`, never `Device`. This survives gateway restart. No raw token or private signing key is stored there. Credentials replaced before this version were not retained, so those old processes still need stopping by hand.

```python
class Registry:
    def mint(self, name: str, now: int) -> str                        # pending row, token_hash = sha256(code); returns the code once
    def credential_for(self, bearer: str, now: int, *, include_revoked=False) -> Credential | None
        # constant-time compare; active-only by default; signed transport and token recognizer opt into retained keys
    def complete_pairing(self, name: str, hello: DeviceHello, now: int) -> tuple[Device, str]
        # one transaction: revoke any paired device with this name, set pubkey and facts, rotate the token, clear expires_at; returns (device, bearer) once
    def active_device(self, name: str) -> Device | None
    def device_by_id(self, device_id: DeviceId) -> Device | None
    def revoke(self, name: str, now: int) -> Device | None
    def set_target(self, session_key: SessionKey, target: str | None) -> None   # id, server, or None to restore the captured default
    def target(self, session_key: SessionKey) -> str | None
    def default_for(self, session_key: SessionKey, target: str) -> str   # insert first configured name, then return it
    def log(self, req: ExecRequest) -> None                           # INSERT, state queued, preview = command[:120]
    def running(self, request_id: RequestId) -> None                 # at claim: UPDATE queued to running once, no terminal metadata
    def close(self, request_id: RequestId, outcome: Outcome, now: int) -> None   # plain UPDATE; the relay already decided
    def mark_stale_lost(self, now: int) -> None                       # at register(): UPDATE requests SET state='lost' WHERE state IN ('queued','running')
    def recent(self, limit: int, session_key: SessionKey | None = None) -> list[RequestRow]
```

## A5. Relay (all live state, one lock)

The relay has one owner, the process receiving device traffic, not every process mounting the plugin API. `plugins.isolation: in_process` loads a terminal provider inside each Hermes process, not inside one shared process. Workers and secondary servers reach the owner through A16.5's local client. The owner's relay holds `handles: dict[RequestId, RemoteProcessHandle]`, `last_seen: dict[DeviceId, float]` `cancels: dict[DeviceId, set[RequestId]]` and `tails: dict[RequestId, bytearray]` (the last `PANE_TAIL_BYTES` of each live request, for the pane) under one `threading.Condition`. Nothing in a worker decides device liveness or request outcomes.

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

Poll handling uses the plugin's `POLL_POOL = ThreadPoolExecutor(max_workers=64)`. Output feeds use a separate `FEED_POOL = ThreadPoolExecutor(max_workers=16)`: held polls must not occupy the workers needed to deliver their commands' output. Neither pool is the event loop's shared default executor. The remaining route work, including JSON parsing, verification and body parsing, uses `asyncio.to_thread`. Disconnect watchers release abandoned polls.

Lost detection: core's `_wait_for_process` never calls the handle's `wait()`; it calls `poll()` in a loop that starts at 5 ms and backs off to 200 ms, so `poll()` is the detector and must stay a plain read: the returncode, then `now - last_seen[device] > OFFLINE_AFTER_S + LOST_GRACE_S`, and on that condition `relay.close(id, Outcome(LOST, 255, ...))`. `wait()` loops on `_done.wait(1.0)` with the same check for the few callers that use it. QUEUED and RUNNING are covered alike, and the thread doing the detection is the one already waiting.

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

def resolve_target(session_key, is_cron, default_target, registry, relay, *, require_contact=True, access=None):
    default_target = registry.default_for(session_key, default_target) if session_key and not is_cron else default_target
    chosen = registry.target(session_key) if session_key else None
    if chosen == "server":
        return Server()
    default = None if is_cron or default_target == "server" else registry.active_device(default_target)
    device = registry.device_by_id(chosen) if chosen else default
    if device is None and (chosen or (not is_cron and default_target != "server")):
        raise EnvironmentConnectionError("Dirtside: this conversation's device is no longer paired.",
                                         retry_hint="Run /dirtside use server, or pair the device again.")
    if device is None:
        return Server()
    access = access or Access()
    sender = access.identity()
    _require_single_sender(sender, is_cron)
    if not chosen and device.owner != sender and not access.privileged(device.owner):
        return Server()
    if not access.can(device, sender):
        if chosen:
            access.require(device, sender)
        return Server()
    if require_contact:
        require_online(device, relay)
    return OnDevice(device)
```

Registration reads `ctx.get_config("default_target", "server") or "server"`, so blank and null defaults mean server. The first non-cron resolution captures that configured name in `session_defaults`, shared by provider, commands, prompt and pane; a reload affects new conversations only. Bare status calls `resolve_target(..., require_contact=False)`; execution requires contact. Only `NoSingleSenderError`, an `EnvironmentConnectionError` subtype raised by the no-sender guard, makes status say no device applies to that turn. Status recognizes the refusal's type without another sender lookup or matching its text. Other errors, including an unpaired default beside an invalid sender, keep their existing status handling. Resolver tests cover choices, defaults, cron, missing or revoked devices and offline devices. `ConversationEnvironment` resolves again at dispatch time against that snapshot and current authorization; `create_environment` has no branch of its own.

Before default-owner fallback, `_require_single_sender` refuses an empty `Access.identity()` with a nonempty route `HERMES_SESSION_USER_ID` on every platform wherever a device applies, chosen or default. Nothing runs on the server. With both identity and route empty, it refuses except on the plugin's eleven listed surfaces: empty platform, `api_server`, `cli`, `desktop`, `gateway`, `kanban`, `local`, `msgraph_webhook`, `tool`, `tui` and `webhook`. Only those user-less turns keep the server fallback. The guard reads the route once and classifies `HERMES_SESSION_PLATFORM` after stripping spaces and lowering case; a source label alone cannot change the decision. Tests cover both normalized forms, core's real surface set at run time and a plugin subset with exactly one core surface unlisted, so additions need review. Explicit server and cron retain their rules. Each resolution reads the sender once for its ownership decisions; the device environment checks current authority again before submission, so losing the sender between those checks cannot turn an admitted device call into a server call.

Within a conversation, each target keeps its own working directory and exported-variable snapshot, starting from the device's home on first use and restoring its state on return; server retains core's local behavior.

The pane target endpoint uses the shared resolver as local for a stored choice or captured non-cron default, reporting server for an untrusted implicit name; cron execution still defaults to server. Missing or revoked defaults return HTTP 404, while an offline paired target remains selectable.

## A8. Protocol

One `Envelope` shape in both directions. `protocol.py` is imported by the gateway and by the device, so there is one implementation of canonical JSON, signing and replay checks.

```python
@dataclass(frozen=True)
class Envelope:
    v: int; kind: str; sender: str; ts: int; nonce: str; body: dict; sig: bytes

def canonical(payload: dict) -> bytes      # json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def sign(key: SigningKey, kind: str, sender: str, body: dict) -> dict
def verify(pubkey: VerifyKey, wire: dict, now: int, guard: ReplayGuard | None) -> Envelope   # raises ProtocolError
class ReplayGuard: ...                     # window 300 s, LRU of 4096 nonces; one cache per peer process
def parse_hello(body) -> DeviceHello; def parse_exec(body) -> WireExec; def parse_chunk(body) -> Chunk; def parse_result(body) -> tuple[Outcome, Chunk | None]   # the optional inline tail (A15.2, R2)
```

Wire bodies carry only what the other side uses:

- `hello` (device to relay, at pairing): `pubkey`, `name`, `os`, `arch`, `home`, `temp_dir`, `agent_version`. Signed with the key whose public half it carries, which proves possession.
- `exec` (relay to device, inside the poll response): `id`, `command`, `script`, `login`, `timeout_s`, `stdin`, `cwd`. No session key, no task id; the device has no use for them.
- `chunk` (device to relay): `id`, `seq`, `data` as base64 of raw bytes, at most `PART_MAX` decoded bytes. The device coalesces its pending 64 KiB reads up to this 2 MiB bound or the first byte's `FLUSH_MS` deadline, whichever comes first. It waits for each post before sending the next sequence number. The relay writes the bytes to the pipe; core decodes once.
- `result` (device to relay): `id`, `state` (`finished` or `refused`), `exit_code`, `duration_ms`, `truncated`, `reason`, and optionally `seq` plus `data`: the unsent tail of the output, at most `PART_MAX`, so a short command costs one post after the poll (A15.2, R2). The relay feeds the tail, then closes.
- The poll response body: `exec` (optional) and `cancel` (a list of request ids). A cancel is a field, not a message.

Both peers keep a `ReplayGuard` with a 300-second timestamp window and at most 4,096 remembered nonces. The gateway uses `GATEWAY_REPLAYS` only after signature verification, so an invalid signature cannot poison it. A retry uses a fresh signed envelope; chunk sequence deduplication and terminal-state checks still prevent duplicate output or completion. These caches are process-local and bounded, not durable replay history across restart or eviction.

Every device route uses `credential_for(..., include_revoked=True)` (401 if unknown), then applies the streamed chunk/result body bound (A10), parses JSON and verifies the credential's signature, 300-second freshness, nonce, sender and route kind. Active malformed messages retain their generic 400; invalid retained proof gets generic 401 and never receives the explicit stop answer. Inside the window that generic body differs from core's rejection of an unknown bearer. A `Pending` credential works only on pairing and verifies against the hello key. A paired credential is looked up again after proof, covering revocation or rotation during verification. A `Revoked` credential receives exact `401 {"detail":"device revoked"}` before body parsing, liveness, owner publication or relay work.

After a gateway restart inside the ten-second window the replay cache is empty, so a captured message younger than 300 seconds can be replayed and receive the stop answer. An active request parses its body and makes one relay or registry call; terminal or unknown work returns 410. JSON parsing, verification and body parsing stay in existing worker threads. Handlers never trust the outer principal as execution authority.

## A9. Device agent

`loop.py` runs one poll thread and at most `policy.max_parallel` executor threads through a `BoundedSemaphore`. The only state shared between them is `running: dict[RequestId, Popen]` under a lock, used by cancel and by shutdown.

```python
def serve(cfg: DeviceConfig) -> None:
    client = httpx.Client(base_url=cfg.gateway_url, headers={"Authorization": f"Bearer {cfg.token}"}, timeout=35)
    delay = 1.0
    while True:
        try:
            wire = client.post("/api/plugins/dirtside/device/poll", json=sign(cfg.key, "poll", cfg.device_id, {}))
            if revoked(wire): kill_all(running); return log("revoked by the gateway; stopping")
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

`post_until_2xx` retries with the same backoff and stops on 2xx, 410 or exact explicit revocation. A 410 ends that request; exact `401 {"detail":"device revoked"}` shuts down the whole agent and cancels running work. Generic 401 responses still retry.

`executor.run` evaluates policy first. A `Refused` becomes `Outcome(REFUSED, 126, ...)` without spawning. Otherwise it spawns `bash -l -c` or `bash -c`, `cwd=req.cwd`, `start_new_session=True`, writes the stdin payload from a separate thread and closes it (a child that fills the output pipe before it reads stdin would otherwise deadlock, which is why core has a writer thread too), reads stdout and stderr merged as bytes through `select`, flushes unsent output `FLUSH_MS` after its first byte, at `PART_MAX`, or at exit, whichever comes first (so a command that ends inside 200 ms makes one post), from the same thread and one post at a time (so `seq` arrives in order by construction), carries the final tail inside the result, stops reading about 300 ms after bash exits with the pipe idle (the same rule as core's drain in `tools/environments/base_output.py`, so a backgrounded grandchild such as `sleep 30 &` cannot hold the request open), enforces the backstop `min(req.timeout_s + 1, policy.max_timeout_s)` with SIGTERM then SIGKILL after 3 seconds, caps output at `policy.max_output_bytes` (default `MAX_OUTPUT_BYTES`) and reports `truncated`. Chunk retries share that capped duration. The gateway owns the requested timeout; the device's extra second lets core cancel first without exceeding device policy (A16.4). A 410 on a chunk or result for a running request kills that request's process group: the gateway no longer wants it. The group is killed only on timeout, cancel, revoke or 410, never after a natural exit: a grandchild such as `uvicorn &` or a `spawn_via_env` job must survive on the device exactly as it survives locally. Only HTTP 401 with the exact body {"detail":"device revoked"} stops the agent; generic core rejection, unknown credentials and foreign 401 responses still retry.

`policy.evaluate(command, policy)` is a pure function with one rule: no deny pattern matches the model's command. It returns `None` or `Refused(reason)`. The wrapped script is never inspected, because it contains the snapshot path, `/dev/null` and whatever the user's login shell references.

What the device enforces, stated plainly: the deny list, the timeout and output caps, the parallelism cap, and the kill switch. It does not confine where a command can dirtside. A folder allowlist cannot be enforced without a sandbox, and claiming one would be a false promise, so v1 does not have one.

Each child gets only set `PATH`, `HOME`, `USER`, `LANG`, `LC_*`, `TERM`, `TMPDIR` and device-owned `env_passthrough` names, without changing the agent's environment or the version-1 wire. Termux additionally keeps the fixed, secret-free system names in `agent/platform.py`, derived from the owner's 2026-11-08 image and app-source probe, including `PREFIX` and `LD_PRELOAD` for termux-exec. Pairing reports `Android (Termux)` in the existing OS field. The full container check is owner-run; physical Android services are untested.

Old four-key policy files mean empty passthrough, while new lists require at most 64 unique ASCII environment names matching `[A-Za-z_][A-Za-z0-9_]{0,127}`.

The names-only `hermes dirtside policy` command shows, replaces or clears passthrough for the next `serve` start, which discloses those names without values.

## A10. Authentication

`DirtsideDeviceAuth(DashboardAuthProvider)` is token-only and noninteractive. Recognition never changes credentials, online state or work. It returns `dirtside` scope for active or valid pending credentials and `dirtside-local` only for the local secret. Revoked or expired pending codes remain unrecognized.

Retained recognition requires `routes.enabled and revoked_at <= now < revoked_at + REVOKE_NOTICE_S`, with the single constant `REVOKE_NOTICE_S = 10`. The persisted time is the credential's first revoke or replacement. Every qualifying signed request inside the window receives the stop answer, including retries after a lost answer and after a parked poll has received one.

The window follows the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window reopens it, and setting it forward closes it early.

When routes are enabled, handlers answer a retained credential with valid proof whenever a request reaches them; only the recognizer applies the ten-second window, and this answer grants no other authority. The two older prepared cores, `84a0301` and `8d7061f`, keep their token gate in front of the registered paths, including loopback without dashboard sign-in.

A retained principal authorizes nothing inside Dirtside, including management, local IPC and dashboard sessions. On released cores, its token gate still accepts that principal on other plugins' registered token routes during the ten-second window, as it did for an active device bearer without its private key. A pairing code also passes those gates until it is used, revoked, replaced by a newer code for that name, or expired, for up to ten minutes; `/dirtside pair` prints it to chat. The local IPC secret also passes those gates and does not expire. Anything running as the gateway OS user, including server-target commands, can read `local.secret`. Dirtside's own registration cannot prove confinement on another plugin's routes.

Session verification and revocation return `None`, leaving interactive dashboard sessions to their own provider.

After auth-provider acceptance, all four device and five unique local paths prefer `ctx.register_dashboard_token_route(path, provider="dirtside", required_scopes=(scope,))`, retaining every registration for unload.

A raising, None-returning or noncallable public seam disables the instance, disposes partial registrations and logs one bounded line without falling back.

The instance gate starts disabled, closes before disposal and guards handlers before parsing even if outer path flags survive or the dashboard gate is off.

After recognizing the chunk or result credential, the route counts streamed body bytes before JSON parsing, independently of Content-Length. The chunk bound is `4 * ceil(PART_MAX / 3) + 1024`, or 2,797,228 bytes, for base64 plus the signed envelope. Results allow another 1,024 bytes for outcome fields and reason, totaling 2,798,252 bytes. An excess returns 413 with "output part too large"; the shared decoded-data parser refuses more than `PART_MAX` with that existing reason. After the bounded read, existing workers do JSON parsing, signature verification and body parsing without blocking the dashboard loop.

Signature, identity and request-ownership checks still precede the feed. The relay consumes one decoded part through its existing memoryview pipe writer, without a second part-sized output buffer. It trims the old pane tail before copying at most the last 4,096 incoming bytes. No large part is first copied into the pane tail and then trimmed. Concurrent same-sequence chunk retries retain the existing serialized, deduplicated feed rather than a new 409.

Pairing under the gate works because the pairing code is itself a bearer the recogniser knows: `/dirtside pair macbook` creates a pending row whose `token_hash` is the code's hash, the device presents the code as its bearer on `/device/pair`, and `complete_pairing` rotates it to the long-lived token in one transaction. There is one credential type and one lookup path.

The two older prepared cores, `84a0301` and `8d7061f`, lack the public method, so only its absence uses one lazy `hermes_cli.dashboard_auth.token_auth.register_token_route` fallback, whose import is disclosed by the catalog validator pending the corrected provider/scoped seam.

Device and local handlers independently refuse each other's credentials and dashboard session credentials under either registration API.

## A11. Routes

Device routes, fixed paths, bearer plus signed body: `POST /api/plugins/dirtside/device/pair`, `/device/poll`, `/device/chunk`, `/device/result`. Desktop routes, dashboard session: `GET /devices`, `GET|PUT /sessions/{key}/target`, `GET /requests`, `POST /pairing`, `POST /devices/{name}/revoke`. Every handler is under 15 lines.

There are no plugin events. The pane polls `GET /devices` and `GET /requests` every 2 seconds while visible and renders the difference. Online state comes from the gateway on every poll, so the pane never needs a previous state.

Local routes use the same `/api/plugins/dirtside` prefix: `POST /local/exec`, `GET /local/stream?id=<id>`, `POST /local/kill?id=<id>`, `GET /local/devices`, `GET /local/requests`. `POST /local/devices` forwards revocation to the owner's live relay. All require a loopback peer and the plugin's local bearer secret, even with the dashboard gate off. Bodies are capped at 8 MiB and parsed exactly. These five paths are token-registered once at startup; stream and kill validate the query id, so execution adds no exemptions. No pane route becomes token-exempt. A secondary server forwards local state reads and revoke; its exec, stream and kill return 409 rather than consult an empty local queue. The local exec parser is the one longer handler, because it is a trust boundary.

Both device lists return exactly `id`, `name`, `online`, `os`, `home`, `last_seen`. Workers and secondary panes use the same connection seam; the pane keeps `/devices` and its dashboard session gate. Its `/requests` uses `/local/requests` for owner state and byte-preserving base64 tails on the private hop, then returns the unchanged pane JSON.

## A12. Slash commands, CLI, prompt section

`/dirtside`, `/dirtside use <name|server>`, `/dirtside devices`, `/dirtside pair <name>`, `/dirtside revoke <name>`. Handlers accept `raw_args: str` and an optional keyword-only core `source`, return `str` and resolve the conversation through `session_identity()`. `/dirtside use` with no argument calls `ctx.ask_choice` with the online devices plus `server`. `/dirtside revoke` calls `relay.revoke` so a running command on that device is cancelled immediately. Targets persist (`targets` table); live handles do not.

`hermes dirtside pair <gateway-url> --name <name> --code=<code>`, `hermes dirtside serve`, `hermes dirtside status`, `hermes dirtside install-service` (launchd on macOS, `systemd --user` on Linux, both idempotent).

`hermes dirtside policy [--env-passthrough NAME ... | --clear-env-passthrough]` edits only device-owned names, never values or gateway policy.

Public session context yields exact bounded printable `platform:user_id` identities. An exception-safe standard-library `find_spec("gateway.approval_actor")` probe checks for a module containing two published plugin API names, `approval_refusal` and `refusal_text`; the API publishes those names, not the whole module. The module is absent at `8d7061f` and `84a0301` and present at `3b42157`; these checkouts do not establish when it arrived. Its presence is the plugin's sign that core binds the actor. Keep module discovery rather than a direct import, which the older cores' validators would report as private. The probe never looks up the unpublished setter. An ungated test binds a turn through core's real binder with different route and actor users and compares the probe with the public reader's actual answer on every core. A wrong "no actor" answer on a core that binds one keeps the first sender after a merge; a wrong "actor" answer on a core that binds none lets an environment actor stand in for the sender. Tests catch both directions on the cores CI runs. Only a capable core reads `get_session_env("HERMES_SESSION_ACTOR_ID", None)`; a `None` value falls back to `HERMES_SESSION_USER_ID`. On the older cores the actor name is never read, so their reader's process-environment fallback cannot replace the bound route user. No version or private variable is inspected. On an actor-capable core an empty actor beside a nonempty route returns missing identity before any host or cron rule. An empty actor and empty route retain the established no-user host and cron rules. Canonical platform `local` with trusted CLI, TUI, Desktop or ACP policy yields `local` only for an empty effective user or this process's exact `uid:<n>`. Policy-free surface `local` additionally needs the actual core-provided non-relay command source, scoped to that call. Direct-Python callers remain host-owned; messaging user-id lookalikes or ambiguous missing context never become host authority.

File-tool limit: core resolves file paths on the gateway; use the terminal for edits on a device.

The direct ACP adapter in all three checked cores omits trusted public provenance. An explicitly selected device therefore refuses there rather than being guessed local; with both identity and route empty, an implicit device default still resolves to server. Canonical ACP policy remains supported.

Device owners, `local` and the at-most-64 unique configured `owners` may discover, use or manage a device, and foreign-name use/revoke refusals match missing names; pairing availability is observable.

With `owners` empty an admitted known sender may pair a new name, while a nonempty list restricts that operation to `local` and listed owners.

Current-turn authorization runs at terminal/file dispatch and again in the independently configured serving owner before submission or history writes, with sender carried only on local IPC.

On 0.23.1 the adapter-shared route may have no user while the current actor still owns a device. Core's real event merge clears that actor when another sender joins a running turn, even in previously copied contexts. A device then refuses on every platform when the route still names a user; when it names none, on every platform outside the eleven listed surfaces. A chosen device still refuses on a listed surface with an empty route, but a default device falls back to server there. Real-binder tests cover canonical CLI `local`, `webhook`, `api_server` and wire-relay-labelled `local` with named routes, with owner and same-sender controls before each merge. Constructed empty-route shared bindings on `webhook`, `api_server`, `msgraph_webhook` and `local` prove the default exception; the Telegram control refuses both choices. The bundled Telegram paths set the shared-session flag on non-DM input. A bundled group-DM path also sets it, but its `dm` classification retains the route user. The relay decoder carries neither that flag nor an event user. These constructed cases do not claim a normal bundled path on the listed surfaces or exercise relay admission. Incoming empty identities follow the route-aware rule in A7 on every checked core; older cores also refuse a named route with invalid or missing identity, including an unprintable webhook user, while valid named senders keep their device. Core invokes `pre_llm_call` once at the start of the turn, not after a merge; device facts already in that turn and its frozen system prompt can remain. The Telegram real turn-loop test keeps those facts and proves that the next call refuses rather than running on the host. Same-sender input keeps authority. Core's real `scoped_turn_actor` gives a queued follow-up its sender, clears that actor if the opener steers into it, and restores the opener on scope exit. Commands, picker visibility, start-of-turn hook facts and newly frozen sections share this lookup. Existing frozen bytes and conversation history remain unchanged.

The older `84a0301` and `8d7061f` cores bind only the route user, whoever opened the running turn. Queued follow-ups run inside that binding (`gateway/run_turn.py`, line 1803; `gateway/run_turn_prepare.py`, line 658). Pending or batched input merges under the first source (`gateway/platforms/base.py`, lines 1723, 1738 and 2486), and threads are shared by default (`gateway/config.py`, line 614 at `84a0301` and line 616 at `8d7061f`). Any multi-sender shared conversation with a device target is unsafe on those cores. Use separate conversations or 0.23.1 or newer. On every core the model also reads participants' shared text; the actor check controls device authority, not input or history privacy. Telegram observe mode appends untriggered participants' text to the transcript (`plugins/platforms/telegram/adapter.py`, lines 5845 to 5861 at `3b42157`).

An inaccessible explicit target fails without server execution. An implicit default must be sender-owned or privileged-owned and normally authorized. A known sender who cannot use it gets the server, even if privileged. An empty identity with a named route instead refuses under a device on every platform. An empty identity with an empty route refuses except on the plugin's eleven listed surfaces in A7, where a device default still falls back to server. This includes user-less API server and direct-ACP-equivalent contexts, not a turn that lost its sender while its route still names a user, nor an unlisted sender-less platform. The initial prompt uses that same resolution.

`current_target_section(session_info)` returns at most 600 characters naming the authorized target, its OS and its home, or the shared configuration warning when another backend is configured. Server behavior is unchanged. Registered as `ctx.register_system_prompt_section("dirtside.target", current_target_section, position="after_memory", max_chars=600)`. Core renders it once per new session and freezes it, so after `/dirtside use` mid-conversation the model learns the change from the command's reply text and the section catches up on the next session. Already frozen bytes are not rewritten.

## A13. Invariants, each with the test that proves it

| Invariant | Test |
|---|---|
| A command never runs on the server when the conversation chose a device | `test_offline_fails_closed`: offline → `EnvironmentConnectionError`, `LocalEnvironment` never constructed |
| Cron never runs on a device by default | `test_resolve_target_table` |
| An actor can use its device on a shared route without a route user; another or empty actor cannot, including through worker IPC | `test_adapter_shared_route_authority_uses_real_core_context`, `test_shared_actor_real_terminal_file_hook_and_frozen_section` |
| A mixed-sender merge with a retained route user, or on an unlisted platform, refuses both explicit and default devices with no server execution or new device requests, including through the real turn loop with its one start-of-turn hook; same-sender input keeps authority | `test_real_merged_event_clears_actor_in_previously_copied_context`, `test_merged_turn_real_dispatch_keeps_route_but_not_first_actor`, `test_real_turn_loop_refuses_after_another_sender_joins` |
| A constructed merge with an empty route on a listed surface keeps default-to-server fallback but refuses a chosen device; Telegram refuses both | `test_merge_with_an_empty_route_keeps_the_listed_default_exception` |
| Commands and the picker use actor ownership, not shared route identity | `test_shared_slash_commands_and_picker_act_for_current_actor` |
| The module-presence probe for the two published names agrees with actual actor binding without gating its own test and survives a moved setter or failed discovery; older bound routes ignore a planted environment actor; an empty actor beside a named route cannot reach host or cron rules | `test_actor_probe_matches_real_binder_without_its_own_gate`, `test_actor_probe_survives_an_unpublished_setter_moving`, `test_bound_turn_ignores_planted_actor_environment`, `test_empty_actor_host_rules_require_an_empty_route`, `test_public_actor_lookup_distinguishes_none_from_empty`, `test_bound_route_fallback_on_older_core`, `test_host_policy_keeps_no_user_and_same_uid_rules`, `test_native_command_source_is_still_required_for_local_actor`, `test_cron_no_user_rule_does_not_grant_an_identified_actor`, `test_configured_owner_privilege_uses_actor_not_route` |
| A queued follow-up uses its own actor, loses authority when the opener steers in, and restores the opener afterward | `test_scoped_followup_actor_changes_and_clears_without_route_change` |
| A non-owner gets the server line under the conversation's captured device default, including after a reload; API/direct-ACP-equivalent calls with both identity and route empty retain server execution with no more device requests | `test_non_owner_default_reports_server_after_owner_prompt`, `test_missing_sender_keeps_server_execution_under_device_default` |
| Empty identity with a named route refuses a chosen or default device on every platform, including an unprintable webhook user on older cores; with an empty route only the plugin's eleven listed surfaces keep server fallback; normalized platforms, source-only direct ACP, explicit server and cron retain their rules; only the no-sender refusal gets the no-device status | `test_listed_platform_merge_refuses_a_device_without_server_fallback`, `test_listed_platform_named_sender_keeps_its_device_on_every_core`, `test_named_route_without_a_sender_refuses_even_without_an_actor`, `test_unprintable_webhook_sender_refuses_a_chosen_or_default_device`, `test_listed_surface_status_uses_the_refusal_not_another_sender_read`, `test_device_default_uses_platform_not_source_for_missing_sender`, `test_missing_messaging_sender_refuses_but_known_non_owner_keeps_server`, `test_default_resolution_uses_one_sender_snapshot` |
| A child launched with planted session and cron variables loses them when it imports test setup; tests may deliberately plant their own values afterward | `test_launch_session_environment_is_not_inherited`, `test_bound_turn_ignores_planted_actor_environment` |
| A request has exactly one terminal state and its pipe closes with it | `test_close_idempotent`: two threads close, one `True`, pipe EOF once |
| `kill()` unblocks a waiting tool thread at once | `test_kill_unblocks_wait` |
| A device that vanishes loses its queued and running requests within grace | `test_lost_covers_queued` |
| Chunks arrive in order; duplicates and late chunks are dropped; late posts get 410 | `test_feed_dedupe`, `test_late_result_410` |
| Revoke cancels that device's live requests and stops its polls | `test_revoke_cancels_running` |
| Revocation needs no parked poll; every qualifying request inside the ten-second window gets the stop | `test_offline_revoked_agent_stops_without_parked_poll`, `test_real_poll_loop_stops_between_polls_only_inside_window`, `test_real_agent_upload_stops_without_an_open_poll` |
| Setting the gateway clock back reopens recognition only inside the old credential's window | `test_gateway_clock_setback_reopens_only_inside_window` |
| Only valid fresh key proof receives the explicit stop answer on a signed route | `test_revoked_key_gets_explicit_rejection_on_every_route`, `test_ungated_router_answers_retained_proof_without_other_authority`, invalid and replay controls in `test_revoke_exit.py` |
| Re-pairing keeps the old credential's original window without affecting the replacement | `test_repair_keeps_retired_key_separate_from_new_device`, `test_different_owner_http_pair_starts_displaced_window`, `test_same_owner_repair_inside_window_keeps_original_end`, `test_repair_never_reopens_first_revocation_window` |
| A pairing code works once, under the gate, and expires; released foreign token gates refuse it when used, revoked, replaced or expired, and admit the local IPC secret | `test_pairing_code_lifecycle`, `test_foreign_gate_admits_only_live_unused_pairing_code` |
| A previous-schema database gains retained storage without reviving long-revoked authority | `test_previous_schema_migrates_without_reviving_old_bearer` |
| Disposing successfully enabled routes closes retained recognition at once | `test_dispose_enabled_routes_closes_retained_window` |
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
| The README numbers are reproducible | `tests/bench.py --loopback` fails a missed A15.1 target locally; CI uses `--report-only` and prints misses without failing |
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
11. Reliability matrix from the plan section 8, run by `scripts/two_machine_matrix.sh`, transcripts saved under `evidence/`. `tests/bench.py` over loopback, LAN and the two-machine rig; its output goes under `evidence/` and into the README with the commit SHA and the date. Remote runs probe a maximum part and warmed small round trip from the device once before the rows, then budget the flood as `max(120, ceil(1.5 * encoded_bytes / measured_bytes_per_second + 32 * round_trip_s + 10))`, record rate, budget and elapsed time in its evidence, and wait command timeout plus 15 s for core's outcome; loopback keeps 120 s and its existing assertions.
12. README, disclosures, catalog YAML, `validate --install-deps` clean.

## A15. Execution strategy: fast where it is felt, exact everywhere

Two sentences define the goal, and every rule below serves one of them. A command on a device returns the same `output`, `returncode` and `cwd` that `LocalEnvironment` would return on that machine. The time Dirtside adds on top of the command itself is one network round trip plus a few milliseconds. Each rule carries the number that justifies it: measured on 2026-11-05 on an Apple silicon Mac under Python 3.15 with PyNaCl, or read from the core source named in the row. The gateway will run an older Python; the numbers are a scale, not a promise.

### A15.1 Where the time goes

The path of a short command such as `pwd`:

| Step | Who | Cost | Source |
|---|---|---|---|
| `execute()` wraps the command: source the snapshot, `cd`, run, emit the cwd marker | gateway, core | string formatting, not measured, well under a millisecond | core's `_wrap_command` in `tools/environments/base.py`, line 473 at the pinned SHA |
| `submit()` logs the request and notifies the parked poll | gateway, plugin | 0.02 ms per SQLite insert and commit at `synchronous=NORMAL` (0.2 ms at `FULL`) | measured |
| The exec rides the poll response | network | no extra round trip; the device's poll was already parked on the Condition | A5 |
| The device verifies the envelope and spawns the shell | device | verify 0.5 ms; `bash -c true` 6 ms; `bash -lc true` 16 ms on this Mac, and more on a profile that loads nvm or conda (not measured) | measured |
| Output and exit code travel back | network | one round trip when the tail fits in the result, two when a separate chunk was needed | A8 |
| The relay checks the signature, feeds the pipe, closes the handle | gateway, plugin | sign 2.2 ms and verify 1.6 ms for a 64 KB body, 0.2 and 0.5 ms for a small one; base64 0.03 ms; the pipe write under 0.1 ms | measured |
| Core notices the exit | gateway, core | `_wait_for_process` polls every 5 ms at first and backs off by 1.5x to a 200 ms cap after about 0.6 s | core's `_wait_for_process` in `tools/environments/base.py`, lines 508 to 581 at the pinned SHA |
| Core stops draining | gateway, core | at EOF, as soon as `close()` shuts the write end; the three 100 ms idle ticks apply only while a grandchild still holds the pipe | `base_output.py` `_drain_fd_select` |

The floor for `pwd` is therefore one round trip plus about 10 ms of work. The poll back-off is core's and the local backend pays it too, but it does not cancel out: the exit is noticed up to one poll interval late, 5 to 200 ms depending on how long the command ran, and that shows up in p95. `tests/bench.py` measures the same command through `LocalEnvironment` and through `DirtsideEnvironment` and reports the difference. The fake device signs and verifies exactly like a real one; otherwise the loopback column would measure nothing.

| Measure | Loopback, fake device | LAN | Internet |
|---|---|---|---|
| `pwd`, p50 added over local | at most 15 ms | at most 40 ms | at most one RTT plus 40 ms |
| `pwd`, p95 added over local | at most 40 ms | at most 100 ms | at most two RTT plus 100 ms |
| 10 MB of output (`head -c 10M /dev/urandom \| base64`) | at least 8 MB/s | at least 8 MB/s | uplink speed, up to 8 MB/s |
| `/stop` to tool return while a command runs on the device | at most 50 ms | at most 50 ms | at most 50 ms; the gateway closes first and the device learns on its next poll |
| Partial output present after a timeout or a cancel | everything written more than `FLUSH_MS` before the kill | same | same |

The original loopback measurement was CPU-bound: one signature per 64 KiB cost about 4 ms of signing and verification (R6). The internet flood instead exposed round-trip cost, addressed by the larger bounded parts in A16.6. A15.4 keeps more invasive throughput work deferred until another measured transfer needs it.

Precedent for the transport, since the choice is the main thing a reviewer will question: GitHub's self-hosted runner receives jobs over an outbound HTTPS long poll held for 50 seconds ([GitHub docs](https://docs.github.com/en/enterprise-server@latest/actions/hosting-your-own-runners/about-self-hosted-runners)), the remote-control feature of a major coding assistant registers its local process over an outbound connection and polls a relay, and VS Code Remote Tunnels keep a persistent outbound connection to a tunnel service ([VS Code docs](https://code.visualstudio.com/docs/remote/tunnels)). One measured comparison puts the per-message latency difference between long polling and WebSockets under 0.3 ms at low event rates on a reused connection; the gap only opens when events arrive faster than one round trip, which a shell command cannot do ([comparison](https://daily.dev/posts/websocket-vs-sse-vs-long-polling-the-real-cost-of-1-000-events-wip1lzawd)). Cloudflare's tunnel daemon opens four outbound connections for availability, not for speed ([Cloudflare docs](https://developers.cloudflare.com/tunnel/configuration)); one device, one connection is enough here.

### A15.2 Rules

- **R1. Dispatch costs no round trip.** The device's poll is parked on the relay Condition; `submit()` notifies and the exec rides the poll response. The device re-polls at once after every response, so a request only ever waits in `QUEUED` for the one round trip of a poll in flight. The agent keeps one `httpx.Client` for its lifetime, so TLS is negotiated once per connection, not per request.
- **R2. Short results travel in one post.** When the unsent tail of the output is at most `PART_MAX`, the device puts it inside the `result` instead of a separate chunk. `pwd`, `ls`, `git status` and a test summary cost one upload. The relay feeds the tail and then closes, under the same single terminal transition.
- **R3. Flush on a clock, finish in the result.** The executor flushes unsent output `FLUSH_MS` after its first byte, at `PART_MAX`, or at exit, whichever comes first, and the final tail rides in the result. Its read wait cannot pass the flush deadline while the shell runs. A command that ends inside 200 ms costs one post (R2). Sending starts within 200 ms when no earlier post is in flight; network and reader backpressure still determine pane arrival. Timeout and cancellation retain core's existing rendering.
- **R4. The feed is lossless and backpressured.** A 64 KB chunk is exactly one pipe buffer on macOS (measured), so a second chunk that lands before core's drain thread is scheduled cannot fit, and a non-blocking writer that ignores the short count drops the remainder: the first draft had that bug. `feed()` now writes every byte, looping on `select` for writability in one second slices on the relay's own pool, bounded by `FEED_BLOCK_S` in total and re-checking terminal state each slice (A5). Because the device posts one chunk at a time and waits for the 2xx, a slow reader slows the device and nothing is dropped. The bound is the only exit: past it the request closes as `LOST` with reason `gateway stopped reading output`, the device gets 410 on its next post and kills the process group.
- **R5. The login shell runs once.** Core's `init_session()` runs the login bootstrap once per environment and later commands run `bash -c` sourcing the snapshot (6 ms against 16 ms here, and far more on heavy profiles). `_persistent = True` keeps that environment across turns. The device runs exactly the `login` flag it is given and never upgrades a command to a login shell on its own.
- **R6. Chunks never write history.** The registry is written at `submit()`, the first claim and `close()`, at `synchronous=NORMAL` (0.02 ms in the original measurement; the request log is the only thing at risk on power loss, and it is a log). The claim writes running beside the handle transition under the Condition. Pipe writes and signature checks happen outside it. The original 64 KiB measurement cost 2.2 ms to sign and 1.6 ms to verify an 87 KB base64 body, about 29 MB/s and 42 MB/s on one core. Day 8 grows parts, not the signature scheme; the benchmark still gates at 8 MB/s. Small messages cost 0.2 to 0.5 ms in the original measurement.
- **R7. Background jobs are left to core.** `process_registry.spawn_via_env` wraps the command as `nohup bash -lc` with a log, a pid file and an exit file under `get_temp_dir()`, then polls with two `execute()` calls every 2 seconds (a log delta and a `kill -0`) and one more to read the exit file at the end. Each poll is one normal request through the relay. Two consequences to know: every background job pays the login shell once (the wrapper's `bash -lc`, outside R5), and the wrapper's `( ... ) &` subshell holds the output pipe, which is exactly the case R10 exists for; without R10 the spawn call (default `timeout=10`) would time out and a group kill would take the job with it. Dirtside adds nothing here; the conformance test proves the path works.
- **R8. Progress is visible where the user is looking.** The relay keeps the last `PANE_TAIL_BYTES` of each live request in memory and `GET /requests` returns it, so the Desktop pane shows output as it streams while the phone waits for the tool to return. Core only shows a foreground command's output when it ends; the pane is the surface that makes a 40-second test run feel alive. A ring of bytes, no new route, no event.
- **R9. Core's limits are the only truncation the model sees.** Core keeps a 40/60 head and tail window at `tool_output.max_bytes` (50,000 by default) and spills up to 5 million characters to disk for recovery, so the foreground path discards everything past about 5 MB anyway. The device still ships everything up to `MAX_OUTPUT_BYTES`, because the internal paths run with full fidelity: `read_file` is a `cat` through `execute()` with `bounded_capture=False`, and truncating it would corrupt a file read. When the device does hit its cap it reports `truncated`, and the environment appends one line, `[Dirtside: output capped at 64 MB on the device]`, so the notice is honest.
- **R10. The device drains like core.** The executor reads through `select` and stops about 300 ms after bash exits with the pipe idle, and it never kills the process group after a natural exit (A9). Without the first half `sleep 30 &` would hold the request for 30 seconds on the device while it returns at once locally; without the second half the backgrounded `sleep`, a `uvicorn &` and every `spawn_via_env` job would die on the device while they survive locally. Both are conformance failures, not performance ones.

### A15.3 Accuracy: the conformance battery

The test that others will not write. Every case runs twice, once with direct relay access and once through the mounted owner's loopback client, and compares against `LocalEnvironment`. Output, return code and the environment's cwd must agree. The signed fake device covers shell and file rows; the real subprocess device covers loss, retry and restart rows in both modes. A separate test runs core's terminal tool in the test process against a subprocess owner with a fake device, so sharing the router's process cannot hide the defect.

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
| device agent killed with SIGKILL mid-command | `LOST` within `OFFLINE_AFTER_S + LOST_GRACE_S`, exit 255, partial output kept |
| a chunk post that fails once and retries | the same `seq` is accepted once; no doubled bytes |
| gateway restarted mid-command | the next poll cancels orphaned work, including silent commands; raced output posts still get 410, and polling resumes without re-pairing |

### A15.4 Deferred, each with the trigger that reopens it

- **Chunk compression.** `zlib` level 1 costs 0.2 ms per 64 KB and shrinks `ls` output six times, random bytes not at all. Add an `enc` field when `tests/bench.py` over a real uplink shows upload time dominating a test-suite run.
- **A heartbeat during a running command.** Loss is detected within 50 seconds (`OFFLINE_AFTER_S` 45 plus `LOST_GRACE_S` 5). Add a 5 second heartbeat post while a request runs when a user reports waiting too long after pulling a laptop's cable.
- **HTTP/2 or WebSocket.** Only if a gateway in front of a proxy cannot hold a 25 second poll; then shorten `POLL_HOLD_S` first.
- **Throughput above 8 MB/s.** The per-chunk signature is the bound (R6). The lever is to sign a running SHA-256 over the stream and verify once at the result, so chunks carry a hash chain instead of a signature, or to pipeline posts with a window of two. Add when `tests/bench.py` shows a real transfer waiting on CPU.
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
- Core forwards `stdin_data` directly for `_stdin_mode = "payload"` (core's `base.py`, line 727 at `84a0301`); there is no separate branch to mirror.
- `requires_hermes` is `>=0.22.7`. The checks establish the payload mode (core's `base.py`, line 272 at `84a0301`), `_persistent` check (core's `terminal_tool_lifecycle.py`, line 270 at `84a0301`), `register_token_route` (core's `token_auth.py`, line 31 at `84a0301`) and provider ABC at pinned core `84a0301`, not at every supported release.

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
- The initial router used a dedicated 16-thread pool for polls and feeds. Day-6 starvation tests replaced it with the separate 64-worker poll and 16-worker feed pools now specified in A5.
- Integration point originally left open: `PUT /sessions/{key}/target` used `set_target(key, None)` for `server`. A16.3 resolves this with the stored sentinel and non-server-default route tests.

### A16.2 Day-3 inside the real core

Built the same night from the A14 step 5 and 6 checks, step 10 and the step 11 script, through the OpenSpec change `dirtside-day3-integration`; 193 tests and the loopback reliability matrix (8 of 8 rows) pass on the owner's run. The tests load the plugin through core's own loader into an isolated home, drive core's `terminal` and file tool entry points against a paired agent subprocess, and mount the router through core's dashboard discovery with the auth gate on. Two defects that only the real core could show, both fixed:

- **Cached environments skipped the offline check.** Core reuses an environment without calling the provider again, so the creation-time check in `resolve_target` did not protect the next command after an outage; the model got a generic timeout. `environment.require_online` now runs before every dispatch in `_run_bash` and reports the offline device with "Nothing was run on the server" (A6, A7).
- **An abandoned long poll could claim work.** When an agent restarted, its old handler stayed blocked in `relay.next` and consumed the next queued request after the connection was gone, while the new agent kept heartbeating. The poll route now watches the ASGI receive channel and passes a cancelled Event into `relay.next`, which wakes every 100 ms while a watcher exists (A5, A11).

Core behaviors to know, none patched around: an explicit `terminal.cwd: "~"` is expanded on the gateway before the provider runs, so the config leaves it unset and the device home applies; file reads through a remote backend are recorded as partial by core (`file_tools.py` takes a version baseline only for host paths), so a remote patch result carries a pagination warning that the local backend does not; the displayed terminal result strips trailing whitespace and bounds large output while the recovery file keeps the shell trailers; concurrent calls with different child task ids share one `session:<key>` environment; a URL-safe pairing code can start with `-`, so the CLI documents `--code=<value>`; the plugin doctor refuses a `TMPDIR` inside the tree it validates. `install-service` renders launchd and systemd user units with pinned paths and private logs, with `--dry-run` and `--remove`; real loading was not exercised. The matrix is a 15-line bash entry over `tools/run_matrix.py`, because signed requests and owned fault injection need Python; evidence transcripts are written under `evidence/` and kept out of git because they carry local paths.

### A16.3 Day-4 user surfaces

The active `dirtside-day4-surfaces` change implements A14 steps 8 and 9 and the A15.1 signed-loopback benchmark against the same pinned core. These amendments supersede the earlier API sketches:

- Targets migrate transactionally to `target TEXT NOT NULL` without a device foreign key, preserving selections and timestamps. `set_target(key, target: str | None)` persists literal `server` or a paired device id; `None` deletes the row. `target(key) -> str | None` replaces the old reader. Both route callers preserve their JSON shapes.
- Core caches environments, so changing the row alone cannot redirect the next command. The provider now returns `ConversationEnvironment`, which resolves on dispatch and keeps per-target delegates and shell snapshots. It disables the host-filesystem shortcut, but core still resolves file paths on the gateway. Removed and offline explicit targets fail closed.
- Core's recorded conversation cwd still crosses targets; the execution boundary does not distinguish it from explicit `workdir`. No heuristic translation is added. A path absent on the new target needs an explicit valid workdir.
- The bound text command, online-device picker and bounded quoted target facts use the existing registration contracts. Core freezes the prompt once; changing targets does not invalidate it.
- Native Desktop discovers `desktop/plugin.js` without another manifest. The opt-in pane uses SDK REST and React Query, stops device/request polling while hidden, and scopes reads and writes by connection, profile, activation and focused durable session key. A foreign or missing owner cannot write through the active gateway.
- The benchmark compares 50 paired commands, verifies all 10,000,000 output bytes and measures early running-command cancellation to tool return. It exposed a fixed 100 ms EOF-before-exit delay in the device executor, replaced by a bounded 10 ms process wait. No core code changes. HTTP and late cancellation are not certified by that measurement; core's adaptive polling can delay the latter by up to 200 ms.
- README contains installation, four-command pairing, security disclosures and dated measurements. The private day-4 report records acceptance outputs and limits. Desktop runtime, physical two-host and real service-manager checks remain unperformed.

### A16.4 Day-5 Linux portability

The active `dirtside-day5-linux` change fixes deadline ownership and test assumptions against the same pinned core. Linux validation remains the owner's GitHub-hosted run.

- Execution and chunk retries use the same pure `device_timeout_s` calculation: the requested timeout plus one second, still capped by device policy. Cancellation does not wait for the backstop. After a gateway restart the device learns at its next poll that its running work is orphaned and stops it; the deadline remains the backstop when the device cannot reach the gateway at all.
- The day-6 correction passes the actual handle to core without holding a finished device timeout. Finalization adds the existing timeout suffix and `hermes_timed_out` flag when device policy expires first, preserving bounded capture and spill metadata. An earlier device-policy stop returns promptly rather than waiting out the caller's longer budget.
- A combined timeout and output cap retains the timeout reason first and the cap notice after `; `. The environment renders the cap notice separately. Ordinary exit 124, loss 255, refusal 126 and cancellation 130 remain distinct.
- Signal tests keep bash and a child alive with a compound command. Pool coverage uses acknowledged dispatch and whichever workers actually start, with ten-second readiness deadlines and the existing five-second cessation bounds. Cwd tests use quoted fixture paths; flush-clock boundaries and partial-output readiness do not depend on fixed sleeps.

### A16.5 Day-7 owner and client

Verified against core 84a0301 and the owner's live transcript from v0.23.0: `gateway/run_api.py` mounts the dashboard in the gateway process through `GatewayDashboardMount`. CLI conversation agents are built client-side, while `tui_gateway/host_supervisor.py` spawns `tui_gateway.compute_host` for TUI, Desktop and web chat. `slash_worker_client.py` spawns a separate slash worker. Each loads its own plugin instance. Messaging-platform turns built by `gateway/session_execution.py` remain in the gateway. `PluginContext` exposes no way for another process to invoke the owner's relay directly.

Any number of processes may import and mount `dashboard/plugin_api.py`. Only authenticated, signature-checked and parsed traffic on `/device/pair`, `/device/poll`, `/device/chunk` or `/device/result` records ownership. Rejected traffic cannot replace discovery or stale request history. Pane, pairing-code, session, history, revoke and local routes never record ownership. The devices' gateway can differ from the unmanaged gateway auto-started by `hermes chat`; that second server remains a client until it receives verified device traffic itself. After a restart, devices are truthfully offline everywhere until the first device poll arrives.

The device-route boundary atomically publishes mode-0600 `owner.json` for the first accepted device message and a changed pid or origin. Fields are `origin`, `pid`, `started`. Uvicorn's ASGI server tuple names the accepted socket's interface, not the wildcard listener, so only its port is used. Discovery always publishes 127.0.0.1, using bracketed ::1 only when an IPv6 connection cannot also reach IPv4 loopback. Real IPv4 wildcard, IPv6 dual-stack and IPv6-only listeners are checked. Host and forwarded headers never affect discovery. A specifically bound non-loopback interface that cannot accept loopback is not an IPC destination.

Registry initialization mints `local.secret`, 32 random bytes encoded as 64 lowercase hex characters, once next to `relay.key`. Both use the existing no-follow, private regular-file and flock boundary. The relay-key lock also serializes initial database setup, preventing simultaneous workers from racing the initial WAL transition. Only the first accepted device message in a new owner performs stale-history cleanup; worker or secondary-router startup never does.

The local routes in A11 recognize the secret through the existing token provider, then independently parse the peer IP, unwrap IPv4-mapped addresses, require loopback and compare the bearer in constant time. They do not trust forwarded headers, cookies or a device credential. The client allows only literal loopback HTTP origins, disables environment proxies and redirects, and never retries ambiguous execution. Before each request, including captured stream and kill destinations, it verifies pid liveness and compares the recorded start epoch with system `ps` output. There is no stale pid-only cache or new dependency. A reused pid with a different start epoch is rejected before the stable secret is sent.

No owner file, a dead pid or a mismatched start epoch means offline for devices, commands, prompts and panes; selected-device execution preserves the existing offline reason. A recorded live owner's connection/read failure or malformed stream uses "Dirtside owner is not running; start the Hermes gateway or dashboard". HTTP failures instead use "Dirtside owner answered <status>: <detail>", with at most 200 printable detail characters. Bare status maps connection errors to text; use resolves the state label before writing its target.

`Relay.connection()` selects direct access only after device traffic in a registered owner, and `dirtside/client.py` everywhere else, including a second serving process. Domain-only test relays remain direct unless explicitly given a client. Environment dispatch, commands, prompts, pane devices, live history/tails and revocation share this seam. Workers query owner memory rather than write SQLite heartbeats. A forwarded revoke cancels a silent owner request immediately.

`ConversationEnvironment._current()` reads the session key and cron flag at each dispatch, using the creation key only when no session is bound.

Each conversation and target owns its cwd and snapshot, with the provider's metadata callback refreshing its selected delegate but never reading or writing core's terminal cwd record.

Core binds turn-local ContextVars through `gateway/run.py:_set_session_env` and `tui_gateway/server.py:_set_session_context`, which public `get_session_env` reads independently of task ids.

The provider keeps transition identity and plugin-owned cwds for the 1,024 most recently selected conversations under a short lock, without retaining facades or snapshots.

History survives idle facade cleanup without consulting core's record, live delegates take priority over evicted history, and server starts from public `ctx.session_cwd()` rather than a device-derived command plan.

Cleanup remembers cwd but drops snapshots with core's environment lifetime, and process restarts retain neither.

New device delegates require contact, while unavailable cwd metadata returns the last known directory and execution stays fail-closed.

Delegate bootstrap holds only the facade's lock, leaving other conversations free to select and execute; the provider lock covers short history and index updates, and a live delegate restores its own cwd if its history was evicted. Optional `get_temp_dir` lookup is registry-free, deferring target resolution until the call inside core's existing fail-soft boundary.

Core still records observed cwd by conversation (core's `tools/terminal_tool_result.py`, lines 223 to 225 at `84a0301`), but an inferred workdir no longer feeds that record back into plugin-owned target state.

Device pairing remains distinct from local IPC: an authenticated non-loopback HTTPS peer can pair with either dashboard gate mode. The device CLI prints HTTP status and at most 512 printable refusal characters, redacts the submitted code and falls back to the status phrase for non-string or non-JSON bodies. The user's public-tunnel refusal was core's "Invalid Host header" check: configure `dashboard.public_url` to the public HTTPS URL on the gateway and restart it; that refusal also prints the same fix in the CLI.

The owner retains an exec handle until stream attachment, including a short result that finishes first. A `FEED_BLOCK_S` attachment timer abandons an unclaimed stream and closes its descriptor. Streaming reads at most `CHUNK_BYTES` at a time. Each raw block has a four-byte big-endian length; zero introduces one trailing JSON outcome line. Arbitrary output cannot impersonate that line, and no final output line must be buffered. Disconnect closes the live request as LOST with "gateway stopped reading output". The client uses the same bounded pipe writer and the same `RemoteProcessHandle`, mirroring output and owner outcomes. An owner-confirmed cancellation completes that handle immediately even if its output pipe is full; the bounded writer releases its duplicate descriptor. The owner detects device loss while reading the stream. Core still owns requested timeout rendering and cancellation, and the device's requested-timeout-plus-one policy-capped deadline remains the backstop from A16.4.

Targets, credentials and request history stay in SQLite. Device polling, signing, live queues, output tails, state transitions and deadline/loss decisions stay in the owner. No core patch, daemon, new dependency or device wire-version change is needed. The conformance battery covers both paths without changed assertions. `tests/bench.py` retains its in-process checks and appends non-gating client p50/p95 pwd latency. The remote matrix worker now imports its case list after path setup, so its documented command does not require PYTHONPATH.

### A16.6 Day-8 slow links and truthful outcomes

`PART_MAX` is 2 MiB; `CHUNK_BYTES` stays 65,536 for device reads and local stream frames. Only pending output grows a part. The executor sends at the part bound or first-byte `FLUSH_MS` deadline, preserves the exited shell's idle drain slices, and carries the final unsent tail in the result. One synchronous upload stays in flight and sequence numbers stay ordered. The shared parser accepts at most `PART_MAX`. Both output HTTP boundaries count bytes before parsing: chunks allow 2,797,228 bytes including base64 and a 1,024-byte envelope allowance; results allow 2,798,252 bytes with another 1,024 bytes for outcome fields and reason (A10). Wire protocol version remains 1: fields, envelope and signing are unchanged; only the output-size bound grows. Both ends need this update for large parts.

A paired device can hold at most one part plus its envelope in memory per post, bounded by these HTTP limits. Transient JSON, signature and base64 allocations are bounded by the same input cap; this is a per-post bound, not an aggregate limit across posts. That work runs in existing worker threads so concurrent polls keep answering. Same-sequence retries can overlap and are still deduplicated by the relay's writer.

For the 64 MiB cap, 32 parts at an assumed 0.7 s cost 22.4 s in round trips. The original 20 Mbit/s assumption put base64 transfer at about 35.8 s and the total near 58.2 s, not an internet measurement. The owner's final two-machine rerun supplied a signed-path probe of 0.268 MB/s and 0.377 s round trip, yielding a 524 s flood budget under A14's rule. The flood command completed in 375.60 s and its whole row in 392.10 s; all eight rows passed. The probe rate is not flood payload throughput. Loopback retains 120 s. The device output cap and gateway timeout ownership from A16.4 are unchanged.

The kill benchmark starts its clock at the RUNNING claim, independent of the first output flush. Waiting for a 64 KiB tail after coalescing would delay that clock to 200 ms and put cancellation in a longer core adaptive-poll slot. The command, exit-130 assertion and 50 ms gate are unchanged.

The claim now writes running to the registry in the same place that the handle enters RUNNING. The update is conditional on the row still being queued, so a recovered claim writes it only once and cannot overwrite a terminal row. A never-claimed request remains queued. Chunks never write the registry. Pane and local history show running before the first output.

| Outcome | Exit code | Rendering |
|---|---:|---|
| Actual timeout | 124 | Core's existing timeout suffix, flag and hint |
| Device policy refusal | 126 | Existing refusal reason |
| Cancellation | 130 | Existing cancellation or core interrupt rendering |
| LOST, device stopped reporting | 255 | Existing reason and partial output |
| LOST, gateway restarted | 255 | Existing stale-history reason |
| LOST, owner unavailable or malformed stream | 255 | Existing owner failure reason and partial output |
| LOST, output reader unattached, disconnected or blocked | 255 | "gateway stopped reading output" and partial output |

Core's exit-code hint table has entries for 124, 126 and 137, not 255. Loss no longer suggests increasing timeout. Only loss expectations change; actual timeout assertions and their rendering remain intact.

---

### A16.7 Catalog-review public boundaries

- Public `tool_execution` middleware marks explicit terminal workdir with a ContextVar and resets it in `finally`, while the facade ignores inferred cwd and preserves explicit transient-directory behavior.
- Middleware can fail open in core, so sender authorization remains independently enforced at each dispatch rather than relying on that marker.
- `ctx.session_cwd()` reads workspace/policy state (core's `hermes_cli/plugin_session.py`, lines 33 to 40 at `84a0301`), not the private terminal cwd table.
- Server delegates use one lazy `LocalEnvironment` handoff to retain core's credential stripping and all other local behavior until a public backend factory exists.
- `EnvironmentConnectionError` is imported only in `environment.py`, remains necessary for core's rendering (core's `tools/terminal_tool.py`, lines 1451 to 1468, 1596 to 1597 at `84a0301`) and needs documenting in the provider contract.
- The corrected token-route seam must use the serving manager's policy scope and refuse non-TokenPrincipal results, the two unresolved assumptions in withdrawn #87462.
- Non-runtime private-core helpers live at `tests/core_runtime.py`, `tests/bench.py` and `tests/bench_client.py`, with callers updated instead of re-export shims or misleading non-test `test_` files.
- Tests use temporary homes outside source, and `tests/test_public_surfaces.py` invokes core's unmodified private-import lint on a clean intended export to require exactly the three disclosed sites once each.

---

### A16.8 Correction 1 boundaries

An implicit device default is eligible only if its owner is the current sender, `local` or a configured owner, and normal dispatch authorization still applies. Even a privileged sender gets server rather than an unprivileged owner's implicit default. Empty `owners` still permits minting an unused default name: names are not a trust grant. Privileged explicit selection identifies an unprivileged owner in the confirmation.

Re-pairing reuses only the latest paired identity for the same owner. A different owner gets the pending row's fresh id; any active previous row is revoked in the same transaction, and old targets remain revoked. `use` and `revoke` hide foreign-name facts like missing names. Pairing deliberately discloses availability: foreign occupied names refuse while free names produce codes.

Core forced discovery disposes old route gates and replaces the public auth provider without remounting the router. BoundaryRoute resolves that provider once before parsing, checks its current gate, and binds it across asynchronous work and copied thread contexts. Local handlers select the same request-bound LocalAPI. Missing, refused and unloaded current providers keep routes closed. The owner-origin cache includes relay identity.

For the same registry, successful forced discovery carries the live registry, relay, provider and its workdir middleware through the previous persistent public auth provider. Its model/protocol and LocalAPI runtime types stay with existing handles, because core evicts the plugin's module namespace. Validated owners and context refresh; each new auth instance has a separate route gate. In-flight work, cached facades, streams and queues survive. A real disabled configuration closes all paths; re-enabling lets the still-mounted router use the new provider. Code updates still require the restart documented in README.

Idle and shutdown cleanup run without a sender context. Only cleanup's generated quoted snapshot removal uses the recorded device owner and an empty preview, through the same serving-owner authorization as ordinary requests. It does not call model execution, accept a model script or consume the command ContextVar.

Re-pairing preserves only a safely readable, valid existing device file's `env_passthrough` names. An unreadable, unsafe or invalid old file instead produces a constant short note and an empty list; only pairing has this recovery path, and configuration reads elsewhere stay strict. It does not copy values; other policy fields retain the previous default reset. On WSL2, Windows `.exe` execution requires enabled interop, its binfmt handler and a usable executable path. `WSL_INTEROP` chooses a live server socket, but `/init` also searches `/run/WSL/<pid>_interop` along the process/parent chain if unset. Passing an existing value can help when fallback fails; it neither enables disabled interop nor repairs a dead socket.

The frozen target section and every authorized turn's fact line are shared model context, not per-sender privacy. Each fact line stays in conversation history and is replayed on later turns. A later participant can receive the device name, OS, home and online state, including stale facts, while their device execution remains denied. `/land` and `/dirtside use` replies also show the home to the whole chat. A server-target command instead runs as the gateway OS user and can read `local.secret` to act as `local` on IPC. Core approvals and sender allowlists must restrict arbitrary gateway execution; device ownership cannot isolate users who can execute as that same account.

### A16.9 Correction 2 lifecycle and defaults

Only a previous provider with runtime_version 2 and the same registry path can supply compatible runtime references. Version 1 and unmarked providers start a fresh Registry and Relay, avoiding reuse of the old credential lookup API.

The relay's existing route gate also governs local ownership: while retired it uses Client rather than old local queues, and its parked polls return without dispatching more work.

Compatible ordinary rediscovery rebinds that gate and preserves live handles, while a cached pre-disable facade reaches the new serving owner through loopback after re-enable.

Local authentication rejects self-forwarding to the same incoming base URL before reading a body, so an unclaimed new runtime cannot recurse through its old owner address; independent secondary-server state forwarding remains supported.

The relay canonicalizes incoming outcome states by value into its own RequestState, and queue, recovery and local-kill comparisons use values rather than generation-specific Enum identities.

The session_defaults table captures the configured default name, including server, on a non-cron conversation's first target resolution, shared across prompt, status, Desktop, dispatch and independent registry instances.

That captured name survives idle recreation, reload and disable/re-enable; new conversations get changed settings, explicit choices remain live, and all resolutions still authorize the current sender.

Existing pre-upgrade conversations capture their default on their first new-version resolution; core's already frozen prompt bytes cannot be reconstructed or rewritten.

Desktop target GET uses the same resolver with local identity and the serving owners list without requiring contact, reporting server for an untrusted implicit device and preserving missing/revoked 404.

Successful pairing reads the old active id under the pairing lock and cancels its live gateway requests immediately if completion installed a different id; invalid pairing and same-owner id reuse do not cancel them.

Only exact HTTP 401 `{"detail":"device revoked"}` shuts the agent down successfully; unknown credentials, generic core unauthenticated errors and transient failures retain retry/backoff.

Pair/hello, poll, chunk and result share the ten-second window from the credential's first revoke or replacement, measured on the gateway's clock (A10). An online device receives the stop on its next valid signed request inside it and exits. A device offline or backing off beyond the window receives core's generic rejection and keeps retrying until stopped by hand. Pairing an already revoked name never starts a new window. Credentials replaced before this version were not retained and need manual shutdown.

Requests without valid signatures, ordinary 300-second freshness, unused nonces and matching sender/kind never receive the explicit stop answer. A different gate or proxy can replace the signal with a generic rejection; that remains retryable, not proof of revocation.

Explicit-revocation tests still require automatic shutdown. The day-8 generic-rejection test now uses an unknown bearer and core's own unchanged response, not a masking helper. The other proxy-fault thread and subprocess tests still use that shared helper and require retry followed by owner-initiated shutdown, retaining existing interrupt and cancellation bounds.

Restart after code updates to replace already-mounted method bodies; a full disable/re-enable is not an in-flight-work continuity promise.

### A16.10 Correction 3 native local authority

Core's public session surface can be `local` without an active local policy, including canonical plugin slash dispatch. C3's empty-or-same-uid rule alone was insufficient because relay ingress accepts wire platform `local`; C4 narrows that branch to the actual non-relay command source. Other uid or arbitrary raw subjects remain ordinary platform-qualified senders; a messaging user id alone never grants host authority.

The native integration tests use the ordinary daemon, same-user control ticket, real CLI session opening and slash dispatch, canonical TUI RPCs, loopback model turns and a signed device agent. They verify local-owned discovery, explicit target selection, server/device cd and export isolation, actual device execution, revocation and refusal of the next command without server fallback. No policy or session identity is fabricated; all three prepared cores run the same test.

The owner-loss test writes its shell pid to an absolute quoted path so retained terminal cwd cannot hide it from teardown. A retained-cwd case checks the process dies and performs scoped safety cleanup even on a red assertion. Its existing wait bounds are unchanged, as is agent.loop.

The optional omission of server session_defaults rows is not applied: missing rows cannot preserve the existing cross-process server-default snapshot after configuration changes. That table remains unbounded. C3 raised the access budget from 71 to its measured 73 lines; C4 budgets are recorded below. Complexity 8 and hard cap 400 remain.

### A16.11 Correction 4 ingress and reload boundaries

At the two older prepared cores, core's `gateway/relay/ws_transport.py`, lines 198 to 238 at `84a0301` and `8d7061f`, reads platform and chat id from wire but stamps the wire-invisible relay flag itself. Chat/session id equality is not authentication. Core's `hermes_cli/plugin_command_dispatch.py`, lines 11 to 32, opts a handler into the actual source keyword; core's `gateway/run_inbound_hooks.py`, lines 288 to 299, supplies it. Commands binds it in an instance-owned ContextVar and resets it in finally. Surface `local` requires source platform value `local`, relay flag exactly false and no detached route, in addition to the existing uid rule. Turns retain their trusted policy surface. Native CLI/TUI slash and turn tests stay the positive control; real relay decode and session binding cover both empty and same-uid wire users, including a matching chat/session id.

Core maps all dashboard and Webapp sign-ins, including forwarded logins, to the host owner in core's `gateway/owner_identity.py`, lines 23 to 44, identical at all three prepared revisions. They therefore act as `local` on POSIX gateways. Windows gateways' `sid:` subjects are not recognized as the host yet.

Local /exec and /stream retry only raw JSON HTTP 401 detail exactly `Dirtside token routes are disabled`, closing each rejection within a fixed three-second monotonic retry window per operation and preserving the request id and captured owner. This gate runs before submission or stream consumption. Other authorization/status/transport failures and partial successful streams are never replayed. The reload regression observes live owner stream attachment before rediscovery; loaded repeats exercise each core separately.

The owner's 2026-11-09 Mac/WSL2 observation established the file-path disclosure in A12: an absolute device read worked, but the write parent was resolved on the Mac gateway. No file-path runtime change or independent two-host reproduction is included.

Only exhausted budgets rise: access 73 to 82, client 173 to 198 and cli 182 to 188 lines, each exactly its measured size. Commands remains within 110. Complexity stays 8 and the hard cap stays 400.

---
### A16.12 Device reach and file-path truth

The standalone device uses lazy optional home lookup and shares the CLI handlers without loading gateway modules. State precedence is DIRTSIDE_HOME, the importable Hermes home path (including explicit HERMES_HOME), then ~/.dirtside. The override expands tilde and resolves to an absolute path from the invocation's working directory, like service rendering. Starting from another directory requires that same absolute override; no cross-process relative-path cache is added. An unknown tilde user returns the usual one-line CLI error. Only the hermes entry point applies the sticky active profile. Legacy service rendering keeps the selected Hermes profile separate from an absolute device-state override, and logs beside that state. HTTPX is now an explicit bounded dependency compatible with the two checked cores.

Plain-text reads and searches with absolute paths reach the device, with the gateway-side resolution limit from A12. Writes, patches and extractable document reads (such as .pdf and .docx) use gateway-resolved paths and work only when no path component is a symlink on the gateway; on a macOS gateway that excludes /home, /tmp, /var and /etc. Use terminal commands for edits and documents under rewritten paths. Terminal commands are not affected, and a Termux home is not affected. This was tested on one shared-disk rig. Core's `tools/file_tools_paths.py`, lines 273, 310 and 334 at `84a0301`, special-cases ssh; lines 147 to 154 expand tilde on the gateway, and line 173 resolves gateway symlinks. Core's `tools/file_tools.py`, lines 442 and 685 at `84a0301`, sends the resolved path for extractable documents and the raw path for plain-text reads respectively; lines 1102 to 1104 send raw paths for search, line 902 sends the resolved write path, and line 1004 sends the resolved patch path. Tilde writes still execute on the device at a gateway-shaped path. Named known-limit tests record both this split and the resolved path received by the device after signature verification. No plugin path rewrite or core edit is added. Latest 8d7061f retains these relevant paths.

The pre_llm_call hook runs once at the start of a turn and resolves the current bound target through the same Access rules as commands, requires no device contact, quotes and bounds data, and fails open on unavailable state. It compares the device home with its gateway-side resolution to choose an absolute-path warning or direct edits and extractable documents through terminal commands, while plain-text reads/searches retain the gateway-path limit. It adds facts to the current user turn through core's public hook without rewriting the frozen prompt. Core stores the composed text as api_content and replays it later, so every authorized turn's fact line stays in conversation history (core's `agent/turn_context.py`, lines 997 to 1013 and 1381 to 1388 at `84a0301`; lines 1089 to 1105 and 1481 to 1487 at `8d7061f`). At the start of a turn, explicit server selection emits the fixed server line. So does an interactive conversation with no explicit choice when its captured device default resolves to server for a known sender, including after a reload changes the configured default. Calls on the plugin's eleven listed surfaces with both identity and route empty also keep that server line. A turn without a sender under a device refuses instead when its route names a user or its platform is unlisted; the hook adds no new facts. An untouched conversation with a server default and an unauthorized explicit device target yield nothing new. Cron does not capture an interactive default. Device selection replies include the absolute home for the whole chat. Publicly registered land and orbit commands call that same Commands instance, declaring and forwarding the actual source through select so native authority and relay refusal match the long form; only successful reply wording changes. Core's `hermes_cli/plugins.py`, lines 649 to 674 at `84a0301`, rejects built-in collisions, and the two older checked cores accept these names through real dispatch.

The shared Access.backend_warning helper lazily reads terminal.backend through public hermes_cli.config.read_raw_config_readonly (core's `hermes_cli/config.py`, lines 1860 to 1864 at both `84a0301` and `8d7061f`). A non-empty string other than dirtside keeps the configured-backend sentence naming the bounded, quoted value and requiring hermes config set terminal.backend dirtside plus a gateway restart. A missing or empty setting uses stripped process TERMINAL_ENV, or local if empty, and warns unless that result is dirtside. Its sentence names the fallback and explains that terminal.backend is not set. Core's `tools/terminal_tool.py`, lines 813 to 817, reads the process fallback, and core's `hermes_cli/config.py`, lines 2082 to 2086 at both revisions, gives the environment precedence when the file omits the setting. A missing or unparseable file returns an empty mapping and follows that rule; a process already bridged to dirtside remains silent if the file becomes unreadable. Non-string explicit values and a reader that raises or exits remain silent. After target authorization the hook and a newly rendered frozen section return only the shared sentence, with no device facts, for saved and configured-default device targets; server selection never calls the helper. This is advice from raw configuration and process environment, not a frozen-session effective-scope check or a hard gate. It does not rewrite already frozen bytes, import core on the device, or add a private core import.

Before the actor change, the merged sizes required budgets of 103 for access, 194 for cli, 115 for the device executor, 58 for registration and 38 for prompt. That review raised only access, from 96 to its then-measured 103 lines. The actor change's current measured budgets are in A3 and the size checker. Native-source and real CLI/TUI regressions cover shortcuts, and real prompt calls cover configured and fallback warnings and unchanged silent cases. Relay-decoded local events receive no new device facts from either prompt path; an implicit default denied to a known sender now gives only the server line.

# Part B. Explanation

## B1. Why a global backend with per-conversation targets

Core freezes `TERMINAL_ENV` into each session's policy in `gateway/session_policy.py` and binds it per turn through `policy_scope()`. That is gateway-internal; a plugin cannot set a different backend per session. So Dirtside is the backend for every session and its cached conversation adapter decides the target at dispatch (A16.3). The cost is that server-target sessions carry Dirtside's provider flags (`is_remote = True`), so their prompt loses the host OS hints. The alternative, switching `terminal.backend` by hand per conversation, defeats the product. The right long-term fix is an upstream seam, which the catalog README invites as an issue.

## B2. Why inherit `BaseEnvironment` instead of writing an executor

`BaseEnvironment.execute()` already does the snapshot sourcing that makes `cd` and `export` persist, the cwd markers, the interrupt handling, the wall-clock backstop, the bounded output capture and the sudo and macOS `open` rewrites. The SSH backend gets all of that from a 300-line subclass whose job is to spawn one local process. Dirtside's subclass is smaller, because it spawns nothing locally. An executor of our own would duplicate roughly 800 lines of core behaviour and drift from it with every release.

## B3. Why the handle is a pipe and not a callback

`_wait_for_process` drains `handle.stdout` on its own thread and fires activity callbacks as bytes arrive. Feeding raw bytes into a pipe gives partial output on timeout, liveness for long commands, one decode in core, and interrupt handling with no Dirtside code involved. A callback design would need Dirtside to reimplement all of that. The Modal and Daytona built-ins use the same pipe shape.

## B4. Why the relay owns live state and the registry is a log

The first draft kept request state in SQLite behind a compare-and-set and ran a sweeper thread. The review found the hole: cancel moved the state but nobody closed the pipe, so every timed-out command would have hung its tool thread. The owner is one process, so one lock is a stronger arbiter than a database row, and it can close the pipe inside the same critical section. The registry now records what happened for the pane and for audit; it never decides anything. The sweeper went with it, because the thread already waiting on a handle can notice the device is gone.

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

The thread that produced this design was explicit that the model must never choose where a command runs. A device-listing tool would be an invitation to do exactly that through prompt injection. The model gets initial target facts from a frozen prompt section and current authorized facts from the public pre_llm_call hook. Hermes already asks the user in chat before a dangerous command and the provider keeps that on, so a second prompt on the device would add a third actor, a timeout policy and a UI on a machine that may have no screen. It stays on the stretch list.

## B11. Why the lints exist

Every "keep files small" and "no scattered conditionals" instruction gets ignored under deadline pressure. `tools/check_sizes.py` and `mccabe.max-complexity = 8` fail CI instead. `TERMINAL`, `Credential`, `Target` and `Decision` are the same idea in type form: the next case is a variant, not a branch.

## B12. What the review cut from the first draft

- The SQLite compare-and-set, the `TRANSITIONS` table and the sweeper thread (B4).
- The `pairing_codes` table, `relay_key` table and the second credential kind (B8).
- The folder allowlist and the path-token scan (B9).
- Eight plugin events, their broadcasts and the pane's subscriptions. The pane polls.
- The settings page. `config_schema` renders the form.
- The `on_session_end` hook. It fires per turn with a session id the relay does not index, and core already calls `cleanup()` on idle reap and session close.
- A `Settings` dataclass and three knobs that were constants. `default_target` was the original setting; the catalog review adds `owners`.
- `session_key` and `task_id` on the wire, `token_hash` on the `Device` type, `script_sha256` and `bytes_out` columns, the poll offset field, a `Backoff` class, `hermes dirtside demo`, the gateway-side replay LRU, and the explicit `skip_container_guards` override (the ABC derives it from `is_container`; the test pins the value).

## B13. What a reviewer should push back on first

Three facts settle on day 0 before any module above is written: whether `register_token_route` is usable from a community plugin (A10 fallback), what cwd reaches `create_environment` with `is_container = False` when `terminal.cwd` is set or Desktop opens a project folder (plan open question 4), and whether `HERMES_SESSION_KEY` is bound inside slash-command handlers and the prompt-section callable, so `session_identity()` returns the same key everywhere. The fourth is the shared-snapshot note: two `execute()` calls on one environment share one snapshot file on the device, as they do on SSH; core serialises environment creation per task, not execution.

## B14. Why the speed work is in the protocol shape, not in the language

Everything Python does on the request path adds up to under 5 ms per small message: the SQLite write, the signature, the JSON, the pipe. A round trip on the internet is 20 to 100 ms, a shell spawn is 6 ms, and core's drain tail is 300 ms whenever a grandchild holds the pipe. Rewriting the plugin in Go or C would remove the few milliseconds and keep the rest, and would cost a second implementation of the protocol and a binary per platform. The rules in A15 remove whole round trips (R1, R2), remove a data loss (R4), keep grandchildren alive (R10), and make the slow parts visible (R8); that is where the time was. The one place CPU does bound the design is bulk output, at about 10 to 16 MB/s per device (R6), and the fix there is a protocol change, not a language change (A15.4). The conformance battery is the other half of the argument: speed that changes an exit code or drops a byte is a bug with a good benchmark.

## B15. Why the owner keeps the relay and the clients stay thin

Moving queues and cancellation into SQLite would not share pipes, wakeups or output readers. It would add competing writers, terminal-state arbitration and another process protocol while still needing IPC for bytes. A new daemon would add deployment and service ownership that Hermes already supplies. Any number of servers may mount the plugin; only the one receiving device traffic owns its relay. All others, including the unmanaged gateway auto-started by `hermes chat`, use the client, so importing or viewing another server cannot steal ownership. Loopback HTTP is the missing seam, not a second execution engine. Clients submit once, copy bytes into core's existing pipe and forward kill. They do not decide online state, run a timeout clock or reproduce the relay's state machine. A local hop costs latency; the benchmark reports it rather than hiding it inside the old in-process numbers.

One device upload stays in flight, with 2 MiB parts amortizing per-post round trips. A remote flood uses the measured link-probe budget from A14, not the discarded 20 Mbit/s assumption in A16.6. Pipelining would add gateway ordering, another buffer and more cancellation states; the existing synchronous post gives ordering and backpressure directly. Revisit that tradeoff only with a measured transfer that needs it.
