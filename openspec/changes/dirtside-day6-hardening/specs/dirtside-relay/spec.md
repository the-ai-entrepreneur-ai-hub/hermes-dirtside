# Spec Delta

## Purpose

Deliver device work reliably without allowing parked polls or captured envelopes to block or consume unrelated work.

## ADDED Requirements

### Requirement: Recover unreceived dispatch
Protocol version 1 SHALL accept an optional signed `running` list of request ids. A subsequent list SHALL recover that device's running requests absent from the list only if they have not begun feeding output. Legacy polls without the field SHALL retain their existing behavior.

#### Scenario: Poll response is dropped
- **WHEN** a dispatch response is lost and the next poll reports an empty running list
- **THEN** the same request is delivered again and executes once

#### Scenario: Execution is acknowledged or has output
- **WHEN** a request is listed as running or has fed a chunk
- **THEN** a subsequent poll does not requeue it

### Requirement: Independent feed capacity
Parked polls SHALL NOT prevent chunk or inline-result delivery within one second when feed capacity is otherwise available.

#### Scenario: Poll workers are saturated
- **WHEN** every poll worker is parked and a device posts output
- **THEN** the output is accepted within one second

### Requirement: Reject captured envelopes
Every device route SHALL reject a repeated signed envelope with HTTP 400 while its sender and nonce remain in the process-wide replay window. Re-signed retries SHALL retain request and sequence idempotence.

#### Scenario: Identical signed poll is replayed
- **WHEN** the same authenticated poll envelope is posted twice
- **THEN** the second post returns 400 without claiming work or refreshing contact
