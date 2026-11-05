# Spec Delta

## Purpose

Expose signed device transport and dashboard-session controls through the plugin API without widening desktop authentication or losing streamed bytes.

## ADDED Requirements

### Requirement: Device trust boundary
Device routes SHALL resolve bearer identity before decoding, verify before online contact, parse after contact and reject uploads for another device's request. Unknown bearers return 401, invalid signed messages return 400 and terminal or unknown requests return 410.

#### Scenario: Wrong bearer before malformed body
- **WHEN** an unknown bearer sends invalid JSON
- **THEN** the response is 401 and no contact is recorded

#### Scenario: Signature before contact
- **WHEN** a known bearer sends an invalid signature
- **THEN** the response is 400 and the device remains offline

#### Scenario: Parsing after verified contact
- **WHEN** a validly signed message has an invalid kind-specific body
- **THEN** contact is recorded and the response is 400

### Requirement: Idempotent output transport
Chunks SHALL be accepted once per sequence and terminal results SHALL feed the optional tail before the single terminal transition.

#### Scenario: Chunk replay
- **WHEN** the same signed chunk is posted twice before completion
- **THEN** both posts are acknowledged but its bytes appear only once

#### Scenario: Late result
- **WHEN** a result arrives after cancellation or completion
- **THEN** the response is 410 and terminal state does not change

### Requirement: Signed nonblocking polls
Poll responses SHALL be signed by the stable relay key, carry dispatch and cancels, and leave the shared gateway event loop responsive while waiting.

#### Scenario: Idle device
- **WHEN** a device holds a poll with no queued request
- **THEN** unrelated dashboard requests continue to complete and the poll returns a verifiable heartbeat

### Requirement: Dashboard controls
Dashboard-session routes SHALL list public device facts, online state and last seen, read and set conversation targets, list recent requests with running output tails, mint pairing codes and revoke devices with immediate request cancellation.

#### Scenario: Desktop operation
- **WHEN** an authenticated desktop selects a paired device, queues work and revokes it
- **THEN** target reads match the selection, the running tail is visible and the live request is cancelled

#### Scenario: Device token on desktop routes
- **WHEN** a device token calls a desktop route with the gate engaged
- **THEN** the response is 401 because the token grants no dashboard session

#### Scenario: Loopback gate off
- **WHEN** desktop requests arrive with the gate off
- **THEN** the routes work without a session while device signatures and bearer checks remain mandatory
