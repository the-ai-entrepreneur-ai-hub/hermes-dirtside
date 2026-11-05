# Spec Delta

## Purpose

Keep device credentials and conversation targets durable while recording requests without deciding their live state.

## ADDED Requirements

### Requirement: Single-use pairing credentials
Pairing MUST mint a pending bearer with a 600 second lifetime and store only its SHA-256 hash. Lookup MUST compare hashes in constant time. Completion MUST rotate the bearer, replace any paired device with the same name and return only an active typed device.

#### Scenario: Pairing lifecycle
- **WHEN** a pending bearer is used before expiry to complete pairing
- **THEN** the old code stops resolving and the new bearer resolves to the paired device
- **AND** an expired, revoked or already consumed code cannot complete pairing

#### Scenario: Concurrent completion
- **WHEN** two workers complete the same pending name
- **THEN** exactly one completes the pending pairing

### Requirement: Durable targets and revocation
Conversation targets MUST persist device identifiers. Clearing a target MUST remove the explicit choice. Revoked or replaced rows MUST never be returned as active devices, while an old target identifier remains available to fail closed.

#### Scenario: Revoke a selected device
- **WHEN** a paired device is revoked after selection
- **THEN** neither its name, identifier nor bearer resolves to an active device
- **AND** its target record still identifies the revoked choice

### Requirement: Request audit log
The registry MUST log queued requests with only a 120 character command preview, record terminal outcomes, filter recent requests by conversation and mark unfinished requests lost at gateway startup.

#### Scenario: Startup recovery
- **WHEN** startup recovery runs with queued, running and terminal rows
- **THEN** queued and running rows become lost with an exit code of 124
- **AND** terminal rows remain unchanged

### Requirement: Private relay key and concurrent storage
The relay seed MUST persist in a regular file named `relay.key` with mode 0600, without following symlinks. Storage MUST use WAL, a 5000 millisecond busy timeout and a separate connection per thread.

#### Scenario: Reopen and worker access
- **WHEN** the registry reopens and multiple threads write independent records
- **THEN** the seed remains unchanged, credentials remain private and every committed record is readable
- **AND** no thread shares its connection with another thread
