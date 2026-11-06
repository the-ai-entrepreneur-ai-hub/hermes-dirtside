# Spec Delta

## Purpose

Let independently loaded Hermes workers use the relay reached by paired devices, without exposing a new remote control surface or changing terminal semantics.

## ADDED Requirements

### Requirement: One discovered owner
Only a process handling device pair, poll, chunk or result SHALL earn ownership and publish a mode-0600 owner record with loopback origin, listener port, pid and verified process start epoch. Imports, pane and local routes MUST NOT earn ownership. Secondary servers MUST use the client. Registration MUST NOT mark another process's requests lost.

#### Scenario: Worker starts during execution
- **WHEN** a worker loads the plugin while the owner has a running request
- **THEN** that request remains live and the worker discovers the same owner

#### Scenario: Owner is absent or stale
- **WHEN** no owner file exists, or its pid is dead or reused
- **THEN** devices, status, prompts and panes report offline and selected-device execution fails with its existing offline reason, never executing on the server

#### Scenario: A recorded live owner fails
- **WHEN** a live owner's transport breaks or its stream is malformed
- **THEN** the request fails with "Dirtside owner is not running; start the Hermes gateway or dashboard"; HTTP status errors instead report "Dirtside owner answered <status>: <detail>" with at most 200 printable detail characters

#### Scenario: Wildcard listener receives interface traffic
- **WHEN** a device reaches a wildcard listener through any interface
- **THEN** discovery publishes IPv4 loopback, or IPv6 loopback only for an IPv6-only listener, and the worker can authenticate there

### Requirement: Private local boundary
Local routes SHALL require a constant-time checked bearer secret and a loopback IP peer after IPv4-mapped unwrapping, independent of the dashboard gate. The secret MUST contain 32 random bytes encoded as hex, be minted once with mode 0600 and never leave the machine. Local execution bodies MUST be bounded and strictly parsed. Stream and kill SHALL use fixed token paths with strictly validated query ids, without per-request exemptions.

#### Scenario: Rejected local caller
- **WHEN** a remote peer, a caller with the wrong secret, or a device bearer calls a local route
- **THEN** the request is refused without execution, with the gate on or off

#### Scenario: Oversized or malformed execution
- **WHEN** an authenticated local caller submits an oversized body, unknown fields, wrong types or an invalid request identity
- **THEN** no execution is submitted

### Requirement: Transparent local execution
Workers SHALL submit execution, receive incremental byte-exact output and its terminal outcome, and forward cancellation through local routes. Core-visible output, status, cwd, timeout rendering, stdin payloads and bounded capture MUST agree with in-process execution. Device protocol version 1 MUST remain unchanged.

#### Scenario: Cross-process terminal
- **WHEN** a non-owner runs pwd, one megabyte of output, a timeout or a cancellation
- **THEN** its results agree with in-process results and the owner's request log contains the corresponding requests

#### Scenario: Reader disconnects or stalls
- **WHEN** a local output reader disconnects or stops consuming
- **THEN** the owner bounds its output buffering to the existing chunk bound and closes abandoned execution as lost, preserving device cessation

#### Scenario: Finished before stream attachment
- **WHEN** a short execution finishes before its worker attaches the output stream
- **THEN** its complete output and terminal outcome remain available to that worker

### Requirement: Authoritative worker state
Status, devices, use, target prompt facts and pane live state in non-owner workers and secondary servers SHALL use the owner's state, including running history and output tails. Device list responses MUST retain their existing fields. Revocation MUST cancel the owner's live requests. Command errors MUST be returned as text, and a failed online lookup MUST NOT silently change a conversation's target.

#### Scenario: Slash worker sees online device
- **WHEN** a paired device polls the owner and a separate slash worker lists or selects it
- **THEN** the worker reports it online and targets the same persisted device

#### Scenario: Worker revokes active device
- **WHEN** a worker revokes a device with a running request
- **THEN** the owner cancels that request without waiting for an output post or timeout

### Requirement: Both paths remain checked
The conformance battery SHALL run every row in in-process and client modes. A subprocess-owner regression SHALL exercise core's terminal entry point from a non-owner test process. Benchmarks MUST report client pwd added latency without gating on that measurement, and the documented remote matrix command MUST work without PYTHONPATH.

#### Scenario: Reproducible checks
- **WHEN** the test suite, loopback matrix and benchmark run
- **THEN** both execution modes are exercised, integrity failures remain failures and client latency is reported next to in-process latency

### Requirement: Dispatch-time conversation context
A cached conversation environment SHALL read the current session key and cron flag at dispatch. It MUST use its creation key only when the current context names no session. Delegates MUST be scoped by conversation and target so shell state and audit identity cannot cross conversations.

#### Scenario: One cached environment serves two conversations
- **WHEN** one environment dispatches in two session contexts in turn
- **THEN** each dispatch follows that conversation's target and records its own session identity

#### Scenario: Cron context changes on a cached environment
- **WHEN** the current cron flag changes between dispatches
- **THEN** default-device suppression follows the current flag, not the creation context

### Requirement: Useful private pairing refusals
The device CLI SHALL show HTTP status and a bounded printable refusal reason without disclosing the submitted pairing code. Device pairing MUST remain available to authenticated non-loopback HTTPS callers.

#### Scenario: Pairing is refused
- **WHEN** the remote endpoint returns an error
- **THEN** the CLI shows the refusal detail or status phrase, redacts reflected pairing credentials and leaves device configuration unwritten

#### Scenario: Core refuses the public hostname
- **WHEN** the pairing refusal contains "Invalid Host header"
- **THEN** the next line tells the user to set dashboard.public_url on the gateway and restart it
