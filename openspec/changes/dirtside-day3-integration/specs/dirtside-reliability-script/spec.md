# Spec Delta

## Purpose

Provide repeatable evidence for the eight reliability situations using an owned gateway and device rig on one or two machines.

## ADDED Requirements

### Requirement: Complete reliability rows
The matrix SHALL check device reporting loss, gateway restart, device restart, concurrent commands, clock skew, output flood, idle long-poll and user interrupt. Each row SHALL print pass or fail and failures SHALL make the overall exit status nonzero.

#### Scenario: Loopback rehearsal
- **WHEN** the owner runs scripts/two_machine_matrix.sh --loopback
- **THEN** it starts an isolated gated gateway and paired device process, runs all eight rows and stops everything it started even after failure

#### Scenario: Two-machine rig
- **WHEN** the owner supplies a gateway URL, device name and control of a dedicated device process
- **THEN** the same checks use that endpoint and device without restarting unrelated user services

### Requirement: Private repeatable evidence
The matrix SHALL save dated transcripts under evidence, exclude credentials and preserve each row's diagnostics.

#### Scenario: A row fails
- **WHEN** a reliability assertion or required control operation fails
- **THEN** its transcript records the failure, remaining independent rows are attempted and the printed row says fail rather than skipped or passed
