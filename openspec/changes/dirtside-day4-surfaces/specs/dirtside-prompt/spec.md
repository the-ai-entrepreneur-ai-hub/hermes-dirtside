# Spec Delta

## Purpose

Give a new conversation bounded execution-target facts without changing its cached prompt during later turns.

## ADDED Requirements

### Requirement: Bounded target facts
A device-target section SHALL name the device, operating system and home, and state that commands run there. It SHALL contain at most 600 characters and treat device strings as data. A server target SHALL contribute an empty string.

#### Scenario: Device facts at session creation
- **WHEN** a new session selects a paired device
- **THEN** the section includes its name, OS and home, even when it is currently offline

#### Scenario: Bound identity takes precedence
- **WHEN** session metadata and the bound conversation identity differ
- **THEN** the section uses the bound conversation's target
- **AND** an unbound callable can use the supplied session id

#### Scenario: Server or missing selected device
- **WHEN** the target is server or a selected device is no longer paired
- **THEN** no other device's facts are substituted

### Requirement: Session-frozen guidance
Target guidance SHALL register after memory with a 600-character limit and SHALL remain frozen for an existing session. A target change SHALL not rebuild that prompt.

#### Scenario: Mid-session switch
- **WHEN** a user selects a different target after prompt construction
- **THEN** the command reply communicates the change while the existing prompt bytes remain unchanged
- **AND** a newly rendered session section uses the current selection
