# Spec Delta

## Purpose

Deliver requests and byte output between core tool threads and a device with one owner of each terminal outcome.

## ADDED Requirements

### Requirement: Request dispatch and one terminal outcome
Requests MUST queue in submission order per device. A poll MUST claim at most one queued request. Exactly one terminal transition MUST set the exit code, signal waiters and close the output writer. Later closes and output for terminal or unknown requests MUST report rejection.

#### Scenario: Concurrent close
- **WHEN** two threads close the same live request
- **THEN** exactly one succeeds, one terminal log entry is written and the reader reaches EOF

#### Scenario: Cancel and revoke
- **WHEN** a live request is killed or its device is revoked
- **THEN** waiting tools unblock immediately with exit code 130
- **AND** cancellation is delivered on the device's next poll, or further polls are refused after revocation

### Requirement: Online and lost detection
Online state MUST derive from a verified device contact within 45 seconds. Both queued and running requests MUST become lost with exit code 124 when a waiting tool observes no contact for more than 50 seconds.

#### Scenario: Missing device
- **WHEN** a tool polls or waits on a queued or running request after the grace period
- **THEN** the request closes lost without a sweep thread

### Requirement: Lossless output with backpressure
Output MUST preserve raw bytes and sequence order, accept duplicate sequences without doubling bytes and retain the latest 4096 bytes for live display. A feed MUST finish within 10 seconds or close lost with reason `gateway stopped reading output`. Close or cancel MUST release a parked feed within one second.

#### Scenario: Slow reader
- **WHEN** three 65536 byte chunks reach a reader consuming 4096 bytes every 100 milliseconds
- **THEN** all 196608 bytes arrive unchanged and each feed stays within its bound

#### Scenario: Reader stops
- **WHEN** a reader stops consuming a live request
- **THEN** the feed bound closes the request lost instead of dropping output

### Requirement: Inline tail precedes close
The final inline output part MUST pass through normal sequence deduplication before the result closes the request.

#### Scenario: Short result
- **WHEN** a short command finishes with all its output in the result
- **THEN** its bytes reach the reader before EOF and no separate chunk post is needed
