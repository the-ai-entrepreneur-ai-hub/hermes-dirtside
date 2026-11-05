# Spec Delta

## Purpose

Keep device execution alive through temporary gateway failures while bounding uploads and stopping deliberately on recognized revocation.

## ADDED Requirements

### Requirement: Report running execution
Each new-agent poll SHALL sign the ids of all accepted requests still executing or delivering their result.

#### Scenario: Command runs across polls
- **WHEN** the device polls while a command or its result post is outstanding
- **THEN** the request id appears in the signed running list

### Requirement: Respect relay feed duration
Output posts SHALL allow five seconds to connect, at least the feed bound plus five seconds to read, and thirty seconds to write, clamped only by a shorter remaining execution deadline.

#### Scenario: Slow but healthy reader
- **WHEN** each chunk takes three seconds to feed before acknowledging
- **THEN** the device sends each chunk once without cancelling the command

### Requirement: Deliberate revocation exit
Only plugin 401 bodies with `unknown device credential` or `device revoked` SHALL stop the agent and cancel running commands. Other 401 responses SHALL back off and continue polling. Deliberate exit SHALL be successful and user services SHALL restart only on failure.

#### Scenario: Foreign unauthorized response
- **WHEN** a proxy or core gate returns another 401 body during execution
- **THEN** execution remains alive and polling resumes

#### Scenario: Recognized revoke
- **WHEN** the plugin returns a recognized revocation body
- **THEN** running commands stop and the agent exits successfully without an automatic service restart
