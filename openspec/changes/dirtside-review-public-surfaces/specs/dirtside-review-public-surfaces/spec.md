## Purpose

Runtime requirements use the public token-route method and two read-only environment imports.

## ADDED Requirements

### Requirement: Exact transitional surface
Core's private-import lint on a clean export MUST report exactly one read-only LocalEnvironment import and one EnvironmentConnectionError import, with no private token-route import.

#### Scenario: test_private_imports_are_exact_transitional_set
- **WHEN** the method core validates the exported plugin tree
- **THEN** only the two read-only environment sites are found and the install scan is safe with an allowed decision

### Requirement: Honest development layout
Non-runtime modules importing core internals MUST live under tests and documented commands MUST remain runnable.

#### Scenario: test_development_entrypoints
- **WHEN** CI, benchmark and matrix entry points load after relocation
- **THEN** they load their helpers without production re-export shims or non-test test_ files

### Requirement: Documented limits
Documentation MUST disclose ownership, device policy and all remaining private seams, and its test count MUST match collection.

#### Scenario: test_review_documentation
- **WHEN** the owner reads commands, security and status
- **THEN** rules match tested behavior and no catalog-unblocked claim is made

### Requirement: Explicit shared-session and host-execution limits
README MUST state what the frozen target section reveals and that server execution can recover the local credential and act as local.

#### Scenario: test_frozen_group_prompt_disclosure_matches_core
- **WHEN** two senders share the real core's frozen prompt snapshot
- **THEN** the second receives the first target facts, device dispatch still refuses, and documentation names the exposed fields

#### Scenario: test_server_execution_limit_is_explicit
- **WHEN** a sender runs server-target commands as the gateway user
- **THEN** the temporary local secret permits local IPC and README points to core approvals and allowlists rather than claiming isolation

### Requirement: Retained-directory subprocess cleanup
Owner-loss test teardown MUST stop its test process even when that process retains a working directory different from its fixture directory.

#### Scenario: test_core_owner_loss_midstream_has_no_timeout_hint
- **WHEN** the owner-loss test runs with a persistent cwd different from its fixture work directory
- **THEN** its bash loop is stopped by the test teardown and no descendant remains

### Requirement: Accurate operator guidance
README and architecture MUST disclose actual core login authority, unsupported Windows host subjects, safe pairing syntax and gateway-side file-path resolution. Core citations MUST NOT resemble repository-local file-and-line references.

#### Scenario: test_core_login_and_device_limits_are_explicit
- **WHEN** the reader follows either operator guide
- **THEN** dashboard/Webapp/forwarded sign-ins act as host, Windows SID host support is absent, pairing uses the equals form and the file-path limit is stated

#### Scenario: test_core_citations_do_not_look_repository_local
- **WHEN** repository markdown is read
- **THEN** core citations use explicit core filenames and prose line references

### Requirement: Descriptor-independent bounded pipe waits
All runtime pipe readiness waits MUST support descriptor numbers above 1024 without changing existing flush, read, feed, cancellation or output bounds.

#### Scenario: test_executor_runs_and_streams_above_select_ceiling
- **WHEN** the parent holds enough descriptors to push the device stdout pipe above 1024
- **THEN** an early chunk streams before the command can finish, the exact late tail arrives, and the soft limit and filler descriptors are restored

#### Scenario: test_relay_writes_above_select_ceiling
- **WHEN** a real relay pipe and duplicated writer are above 1024
- **THEN** bytes arrive exactly and the terminal result remains successful

#### Scenario: test_local_stream_reads_above_select_ceiling
- **WHEN** local streaming consumes a real high-numbered stdout pipe
- **THEN** its binary length framing and successful outcome remain exact and the consumer closes

### Requirement: Explicit test descriptor ownership
An autouse guard MUST measure descriptors before and after each test on Linux and macOS and fail growth above a stated margin of two, without forced garbage collection or blanket descriptor closure. Test fixtures MUST close their database connections, pipes, subprocess handles and started LSP event loops at the owning lifetime.

#### Scenario: test_descriptor_guard_checks_actual_teardown
- **WHEN** a subprocess test closes four allocated descriptors or intentionally leaves them open
- **THEN** the same real guard passes the closed case and rejects the four-descriptor leak

#### Scenario: test_owned_core_closes_stdin_after_external_exit
- **WHEN** an owned core exits before cleanup and cleanup runs twice
- **THEN** stdin, stdout and the log are closed even though the process is already dead

#### Scenario: test_owned_agent_closes_stdin_after_external_exit
- **WHEN** an owned adapter agent exits before repeated stop calls
- **THEN** its stdin and log close without depending on process liveness

### Requirement: Authenticated revocation without a parked poll
Automatic revocation shutdown MUST work without an admitted poll during the ten-second window from the credential's first revoke or replacement, with routes enabled. The window follows the gateway's clock in whole seconds. Setting that clock back into the window reopens it, and setting it forward closes it early. Every valid signed request inside it MUST receive the stop, including retries. Generic core rejection MUST retain retries; devices missing the window need manual shutdown.

#### Scenario: test_parallel_limit_keeps_poll_cancellation_live
- **WHEN** two commands run, a queued command starts after cancellation, and revocation interrupts an admitted poll
- **THEN** parallelism and cancellation remain live, every process group stops, the agent exits within the unchanged five-second bound, and retained stdout pipes close

#### Scenario: test_offline_revoked_agent_stops_without_parked_poll
- **WHEN** the real agent reconnects inside the ten-second window after being revoked while offline
- **THEN** qualifying proof receives the stop and the subprocess exits successfully without a parked poll

#### Scenario: test_real_agent_upload_stops_without_an_open_poll
- **WHEN** a qualifying chunk or result upload reaches a recognizable revoked credential
- **THEN** fresh key proof receives explicit revocation and shuts down real execution

#### Scenario: Window start and proof limits
- **WHEN** a name is paired after it was already revoked
- **THEN** its old credential keeps the time of its first revoke or replacement and re-pairing never starts a new window
- **AND** pre-version replacement credentials were not retained and need manual shutdown
- **AND** foreign bound routes refuse the bearer, legacy unbound routes skip Dirtside while it has a bound policy, and it has no active authority inside Dirtside
- **AND** invalid proof never receives the explicit stop answer; bad retained proof and unknown bearers have different generic bodies

#### Scenario: test_restart_keeps_window_and_resets_replay_guard
- **WHEN** the gateway restarts inside the window
- **THEN** its empty replay cache permits a captured message younger than 300 seconds to receive the stop answer
