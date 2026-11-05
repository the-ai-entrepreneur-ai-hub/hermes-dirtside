# Spec Delta

## Purpose

Preserve core execution semantics while making remote terminal failures visible and cleaning up device session artifacts.

## ADDED Requirements

### Requirement: Visible terminal reasons
Every nonempty terminal reason SHALL reach tool output as one trailing `[Dirtside: <reason>]` line, except an explicit device timeout rendered with core's timeout suffix.

#### Scenario: Device spawn fails
- **WHEN** a request's device cwd does not exist
- **THEN** the tool returns exit 126 with the spawn reason visible

#### Scenario: Device stops reporting
- **WHEN** the relay marks a request lost
- **THEN** the tool output includes `device stopped reporting`

### Requirement: Prompt device timeout
A device-reported timeout SHALL return promptly with exit 124, core's exact requested-duration suffix and `hermes_timed_out`, preserving bounded capture and spill metadata.

#### Scenario: Policy timeout is shorter
- **WHEN** a thirty-second request hits a two-second device cap
- **THEN** the tool returns within five seconds rather than waiting thirty seconds

### Requirement: Best effort snapshot removal
Cleanup SHALL remove the session snapshot and its temporary variants through the online device within a five-second request budget. Every cleanup failure SHALL be swallowed.

#### Scenario: Online device cleanup
- **WHEN** an environment with a device snapshot is cleaned up
- **THEN** its snapshot and temporary variants no longer exist on that device

### Requirement: Attribute probes have no dispatch side effects
Unknown attribute probes SHALL inspect only the last-resolved delegate and SHALL NOT read the registry or create a delegate. Work methods SHALL still resolve the current conversation target.

#### Scenario: Unknown optional attribute
- **WHEN** a caller probes `getattr(environment, "nope", None)`
- **THEN** it gets `None` without registry reads or connection errors
