# Spec Delta

## Purpose

Expose truthful request history and terminal outcomes so users and core do not confuse lost commands with commands that reached their timeout.

## ADDED Requirements

### Requirement: Persist the device claim

Request history SHALL change from queued to running at the device's claim before any output arrives, without per-chunk history writes. A request never claimed SHALL remain queued until a terminal transition.

#### Scenario: Claimed silent command

- **WHEN** the device claims a queued command without sending a chunk
- **THEN** the registry, pane and local history report running without terminal metadata

#### Scenario: Unclaimed command

- **WHEN** a queued command has not been claimed and no terminal event occurred
- **THEN** its stored state remains queued

#### Scenario: A lost poll response is recovered

- **WHEN** an unstarted claim is safely offered again after a lost poll response
- **THEN** history is not rewritten per chunk or returned to queued
- **AND** later completion still records its terminal outcome

### Requirement: Distinct lost exit status

Every lost outcome SHALL report exit 255 with its existing reason text and retained partial output, without a core timeout hint. Real timeouts SHALL remain exit 124 with core's timeout suffix, policy refusals 126 and cancellation 130.

#### Scenario: Device stops reporting

- **WHEN** the device exceeds the existing loss window
- **THEN** the waiting command returns 255 with "device stopped reporting" and its partial output

#### Scenario: Gateway restarts

- **WHEN** the owner recovers history for queued or running work after a restart
- **THEN** those rows are lost with exit 255 and "gateway restarted"

#### Scenario: Owner becomes unavailable or stream is malformed

- **WHEN** a worker loses its owner mid-stream or receives a malformed stream
- **THEN** it returns 255 with the existing owner-unavailable reason and any already received bytes

#### Scenario: Output reader stops

- **WHEN** an unattached, disconnected or blocked output reader makes delivery fail
- **THEN** the request is lost with exit 255 and "gateway stopped reading output"

#### Scenario: Actual timeout

- **WHEN** the requested timeout or device-policy timeout expires
- **THEN** core still renders exit 124 and its existing timeout suffix and metadata
- **AND** increasing a timeout is never suggested merely because a request was lost

### Requirement: Cancel orphaned running work on poll

After recovering dispatches under its condition, the owner SHALL include each reported running id absent from its live handles in that device's cancel list in the same poll reply. This rule SHALL preserve every known live handle, add nothing for legacy polls without a running list, and never rewrite terminal registry history.

#### Scenario: A silent command outlives the gateway

- **WHEN** a device reports a running id unknown to the replacement owner
- **THEN** that poll reply includes the id in cancels without waiting for output or the command deadline
- **AND** repeated reports repeat the cancel until the device drops the id

#### Scenario: Work is still owned

- **WHEN** the reported id has a live queued or running handle
- **THEN** this rule does not cancel it

#### Scenario: A legacy or empty poll

- **WHEN** no running list or an empty list is supplied
- **THEN** the orphan rule adds no cancel ids and existing explicit cancels remain unchanged

#### Scenario: Gateway-restart matrix

- **WHEN** the gateway restarts during a silent sleep 600 carrying timeout=600
- **THEN** the device process is gone within one poll interval plus 10 s of the replacement owner becoming ready
- **AND** the existing ticking restart phase still passes and the matrix retains eight rows
- **AND** the device deadline remains the backstop when the gateway cannot be reached

#### Scenario: Revocation authenticates a fresh poll without a parked request

- **WHEN** a revoked device's valid signed poll reaches retained-key verification inside 10 seconds from its first revoke or replacement
- **THEN** the gateway returns exact {"detail":"device revoked"} and HTTP 401, and the agent stops successfully
- **AND** the ordinary signature, 300-second freshness, nonce, sender and kind checks run first
- **AND** every qualifying retry inside the window receives the answer, including after a parked poll has received one
- **AND** generic core and foreign 401 responses still retry without stopping live work
- **AND** the existing five-second revocation check remains unchanged

#### Scenario: test_restart_keeps_window_and_resets_replay_guard
- **WHEN** the gateway restarts inside the persisted window
- **THEN** its empty replay cache permits a captured message younger than 300 seconds to receive the stop answer

#### Scenario: Late device needs manual shutdown
- **WHEN** a device is offline or backing off beyond the window, or its credential was replaced before this version retained it
- **THEN** generic rejection keeps it retrying until manually stopped
- **AND** pairing an already revoked name never reopens its old credential's window
- **AND** during the window other plugins' released core token gates still accept the bearer, but it authorizes nothing inside Dirtside
- **AND** invalid proof never receives the explicit stop answer; bad retained proof and unknown bearers have different generic bodies
