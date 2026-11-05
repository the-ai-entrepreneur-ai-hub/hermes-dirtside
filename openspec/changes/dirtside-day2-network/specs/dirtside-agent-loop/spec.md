# Spec Delta

## Purpose

Let a paired personal device execute signed gateway requests over outbound HTTP while preserving local shell behavior and reliable output.

## ADDED Requirements

### Requirement: Verified dispatch
The agent SHALL reuse one HTTP client, verify every poll with its pinned relay key and replay protection, and execute at most the configured parallel limit.

#### Scenario: Valid dispatch
- **WHEN** a paired agent polls and a command is queued
- **THEN** the command executes with its supplied cwd, script, login flag and stdin

#### Scenario: Invalid relay message
- **WHEN** a poll has a bad signature, wrong identity, malformed body or replayed nonce
- **THEN** no command executes and polling backs off from 1 second to at most 30 seconds

### Requirement: Lossless uploads
The agent SHALL upload chunks sequentially, retry unchanged chunk sequences after errors and carry the unsent tail inside the terminal result.

#### Scenario: Upload fails once
- **WHEN** the first chunk upload receives 503 after its bytes were accepted
- **THEN** retry delivers no doubled output and the command completes byte-exactly

### Requirement: Cancellation and shutdown
The agent SHALL cancel running groups on gateway cancel, revocation, terminal upload rejection and SIGINT or SIGTERM, while leaving natural background jobs alive after normal completion.

#### Scenario: Stop a running command
- **WHEN** a sleep command is cancelled
- **THEN** the gateway returns exit 130 immediately and the device process is gone within 5 seconds

#### Scenario: Revoked bearer
- **WHEN** a device post receives 401
- **THEN** every active execution is cancelled before the agent stops

#### Scenario: Process signal
- **WHEN** the foreground agent receives SIGTERM or SIGINT
- **THEN** active groups are stopped and the agent exits cleanly

### Requirement: Gateway and device failure recovery
The system SHALL retain flushed partial output when a device disappears and permit a paired agent to reconnect after gateway restart without pairing again.

#### Scenario: Agent killed
- **WHEN** a subprocess agent is killed with SIGKILL during a command
- **THEN** the request becomes LOST with exit 124 within the offline window plus grace and keeps flushed output

#### Scenario: Gateway restarted
- **WHEN** a new relay replaces the old relay on the same registry during a command
- **THEN** the next upload receives 410 and stops that execution, and a later poll succeeds with the existing token and pinned key
