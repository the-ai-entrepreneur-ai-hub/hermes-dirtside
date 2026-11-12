# Design

## Context and evidence

On 2026-11-08, core's validator reported 29 findings: six runtime sites and 23 development-tool sites. Non-runtime modules importing internals now live under tests, with their callers and documented entry points updated rather than hidden by production re-export shims or misleading test filenames.

The original 2026-11-08 review used the earlier core lint and disclosed its then-existing import inventory. On the test core, a clean export has exactly two read-only environment imports, LocalEnvironment and EnvironmentConnectionError, with no private route import or private attribute findings. The install scan reports a safe verdict and an allowed decision.

README and architecture explain the minimal environment, device-only passthrough, sender ownership, public middleware and the two read-only environment imports. Token routes require the public context method.

Rejected: teaching the validator to ignore tools hides debt; a source-pattern substitute is not the catalog check; renaming non-tests test_ is misleading; claiming released cores implement the seam is false.

## Regression coverage

- `test_private_imports_are_exact_transitional_set`: Exact transitional surface.
- `test_development_entrypoints`: Honest development layout.
- `test_review_documentation`: Documented limits.

Core's actual email extractor preserves quoted local parts with ASCII spaces. Native identity preserves bounded printable ids, and migration coverage includes queued and finished request history.

## Shared prompt and host execution

Pinned core's `agent/system_prompt.py`, lines 113 to 135 at `84a0301`, freezes plugin sections at first render and lines 138 to 167 restore persisted bytes. All participants can receive the first render's device name, OS, home and online state, including stale or unauthorized facts, through the shared model context. Per-turn dispatch still checks the sender. test_frozen_group_prompt_disclosure_matches_core exercises the real frozen accessor and denies the later sender's execution.

Server-target commands execute as the gateway user, can read local.secret and can authenticate local IPC as local. This is not an ownership boundary against a sender with arbitrary server execution; core approvals and messaging allowlists decide that trust. test_server_execution_limit_is_explicit demonstrates it only in temporary homes and checks the threat-table disclosure.

Official WSL documentation https://wsl.dev/technical-documentation/interop/ says WSL_INTEROP selects the interop server; without it /init tries /run/WSL sockets up the parent chain. Passing its existing value supports Windows .exe tools when fallback cannot reach a live server; enabled interop and an executable path are still required. No new WSL-host execution is claimed.

## Runtime continuity and defaults

Configured defaults are snapshotted while explicit target changes remain live; reload cannot rewrite an already frozen prompt. The two read-only environment imports and host-execution trust limits remain.

Generic-auth retry remains mandatory, but retained paired credentials now reach proof-first revocation through the fixed signed routes. Only freshly authenticated revoked proof gets the explicit automatic-shutdown signal; no active or local authority is restored. Immediate gateway cancellation, secondary-server forwarding and existing numeric bounds remain unchanged. Tests deliberately replacing the signal with generic 401 still require retries and owner-initiated shutdown.

## Native identity and retained state

Native identity, retained-cwd cleanup, numeric bounds and default snapshots remain unchanged. Server rows remain necessary because absence cannot distinguish an earlier server snapshot from a new conversation.

## Login and file-path boundaries

Dashboard, Webapp and forwarded logins act as the host owner. Windows sid: subjects are unsupported by the POSIX identity rule. Pairing uses --code=<code> because codes may start with a hyphen. Chosen-machine claims apply to terminal commands; core resolves some file-tool paths on the gateway. Re-pair recovery preserves names only.

## Descriptor ownership and revocation

All three former runtime select.select calls rejected real pipes above descriptor 1024 on macOS too. A shared readiness helper uses a scoped DefaultSelector per wait. This preserves the executor's min(0.1, flush wait), the local reader's 0.1-second slice and the writer's min(0.25, remaining deadline). The worker executing an asynchronous wait owns and closes its selector, even if its awaiting task is cancelled.

The guard counts valid descriptors under /proc/self/fd on Linux and /dev/fd on macOS before fixture setup and after teardown, allowing at most two bounded framework/startup descriptors. It neither collects garbage nor closes arbitrary descriptors. A separate fixture owns only test Registry connections through an ExitStack. Its local sqlite3 proxy permits cross-thread close after dependent fixtures have joined their workers; the production connection factory, thread-local cache, transaction checks and default thread affinity are unchanged. Direct SQLite inspections use closing plus the existing transaction context. The archived old-registry fixture connection has its own finalizer. Native TUI admission polling closes each inspection connection instead of waiting for cyclic garbage collection. Rig cleanup closes stdin even when a child has already exited, and the parallel network test closes the stdout handles its middleware retains.

Profiling through 2026-11-10 found three descriptors from core's lazy LSP event loop after local file operations. Its fixture calls the existing shutdown_service API before guard measurement. Core's logging handlers and owner-death supervisor are bounded, and the one native-test UNIX socket had mDNSResponder as its kernel-reported peer. That 934-test profile finished with descriptor start/end 14 and peak after-test 15.

The supplied Linux stdout from that investigation reports the network timeout alone (926 passes). Its count file has a 47563-byte NUL prefix. The first 165 records and final 372 intact records cover 537 of 927 tests; 390 are unavailable. Native TUI polling adds 355 in the intact Linux sequence, agreeing with the macOS SQLite ownership diagnosis. The maximum observed count is 423; the missing portion has no measured maximum.

The earlier network investigation reproduced its exact five-second proc.wait failure with 25 gateway descriptors: a poll held before core authentication received generic Unauthorized and correctly retried, while an already verified poll produced explicit revocation and exit in about 0.134 seconds. CI supplied no wire trace, so that run's precise response remains an inference. The earlier synchronization covered only parked polls. Recognition now uses the ten-second window from the credential's first revoke or replacement while routes are enabled. The window follows the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window reopens it, and setting it forward closes it early. Every qualifying signed request gets the stop, including after a parked poll or lost reply. Cancellation, parallelism, process-group and five-second assertions remain unchanged; the day-8 generic control exercises an unknown bearer through core itself.

An offline or backed-off agent missing the window keeps retrying until manually stopped. Pre-version replacement credentials were not retained and need manual shutdown. Pairing an already revoked name never starts a new window for the old credential. Inside the window the bearer authorizes nothing inside Dirtside. Foreign bound routes refuse it, and legacy unbound routes skip Dirtside while it has a bound policy. Disabled or inactive registrations prevent recognition even after that last policy is gone. A longer window is possible on the bound gate and is not part of this version.

Invalid proof never receives the explicit stop answer. Bad retained proof and an unknown bearer get different generic bodies inside the window. A restart empties the replay cache, so a captured message younger than 300 seconds can be replayed and receive the stop answer inside the persisted window.
