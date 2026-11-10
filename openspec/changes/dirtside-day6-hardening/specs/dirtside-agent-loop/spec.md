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
Only HTTP 401 with exact body `{"detail":"device revoked"}` SHALL stop the agent and cancel running commands. Unknown-credential, generic and foreign 401 responses SHALL back off and retry. Deliberate exit SHALL be successful and user services SHALL restart only on failure.

#### Scenario: test_real_poll_loop_stops_between_polls_only_inside_window
- **WHEN** a revoked or replaced device returns
- **THEN** every qualifying signed request inside 10 seconds from its first revoke or replacement receives the stop answer under either registration API
- **AND** offline or backed-off devices missing the window retry until manually stopped; pre-version replacements were not retained
- **AND** pairing an already revoked name never starts another window for its old credential
- **AND** inside the window the bearer still passes other plugins' released core token gates but authorizes nothing inside Dirtside

#### Scenario: test_independent_device_clock_gets_notice
- **WHEN** a device signs in the revoke second or its clock is 60 seconds behind or ahead
- **THEN** valid 300-second-fresh proof receives the stop inside the window

#### Scenario: test_restart_keeps_window_and_resets_replay_guard
- **WHEN** a gateway restarts inside the window with an empty replay cache
- **THEN** a captured message younger than 300 seconds can be replayed and receive the stop answer

#### Scenario: Foreign unauthorized response
- **WHEN** a proxy or core gate returns another 401 body during execution
- **THEN** execution remains alive and polling resumes

#### Scenario: Recognized revoke
- **WHEN** the plugin returns a recognized revocation body
- **THEN** running commands stop and the agent exits successfully without an automatic service restart
