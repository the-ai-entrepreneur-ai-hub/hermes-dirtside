# Spec Delta

## Purpose

Run core's existing wrapped shell and file operations on the selected device without changing their output semantics.

## ADDED Requirements

### Requirement: Core process-handle compatibility
Execution MUST return a process handle with a real readable output descriptor, poll, wait, kill and return-code behavior. Raw bytes MUST be decoded only by core. Waiting with an expired caller deadline MUST raise a timeout rather than returning a false terminal result.

#### Scenario: Multibyte boundary
- **WHEN** a three-byte UTF-8 character crosses output chunk boundaries
- **THEN** core returns the same characters as local execution without replacement bytes

### Requirement: Device shell state
The device home MUST replace a literal initial `~`. Core's login snapshot MUST initialize once, subsequent calls MUST preserve cwd and exported variables, and stdin MUST travel as a payload. The environment MUST remain persistent across turns and MUST NOT bypass approvals.

#### Scenario: Persistent shell
- **WHEN** one call changes directory and exports a variable
- **THEN** a second call observes both changes on the device

#### Scenario: File payload
- **WHEN** core writes and reads a one megabyte file through shell file operations
- **THEN** the content is byte-exact, including text without a final newline

### Requirement: Local conformance
The in-process signed device path MUST match core local output, return code and final cwd for all day-1 cases. Random output MUST use one shared random input for both runs so equality remains meaningful.

#### Scenario: Conformance battery
- **WHEN** both environments run pwd, persistent cd and export, exit 3, a missing command, merged stderr, split multibyte text, random base64, one megabyte of sequence output, timeout, file write/read, patch/search, a missing directory, a background grandchild, background job polls and stop
- **THEN** each case returns equal output, return code and final cwd
- **AND** timeout and stop terminate the device process while natural exits leave background children alive

### Requirement: Honest output cap
When device output exceeds its cap the environment MUST append an explicit device-cap notice rather than silently returning incomplete file content.

#### Scenario: Device truncation
- **WHEN** a device reports truncated output
- **THEN** the result includes a notice naming the device output cap
