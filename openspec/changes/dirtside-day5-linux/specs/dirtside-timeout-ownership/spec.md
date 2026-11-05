# Spec Delta

## Purpose

Give timed-out device commands the same observable result on macOS and Linux, regardless of which deadline fires first, while retaining a bounded device-side safety stop.

## ADDED Requirements

### Requirement: Gateway owns the requested timeout
The gateway SHALL enforce the caller's requested timeout. The device SHALL use a backstop of the requested timeout plus one second, capped by its maximum timeout policy. Execution and output-upload retries MUST use this same capped duration. Cancellation MUST NOT wait for the backstop.

#### Scenario: Gateway remains available
- **WHEN** a command exceeds its requested timeout and the policy cap permits the grace
- **THEN** the gateway returns a timeout at its own deadline and sends cancellation to the device
- **AND** the device stops the whole command process group

#### Scenario: Gateway no longer cancels
- **WHEN** a one-second request continues without gateway cancellation and the policy cap is greater than two seconds
- **THEN** the device starts stopping the process group at its two-second backstop

#### Scenario: Policy overrides the grace
- **WHEN** a request has a ten-second timeout and the device policy caps execution at one second
- **THEN** the device starts stopping the process group after one second, without adding grace beyond that cap

#### Scenario: Uploads keep failing
- **WHEN** output-upload attempts fail throughout the device's capped duration
- **THEN** retries stop at that deadline and the command process group is stopped

### Requirement: Timeout results do not depend on the winning deadline
An explicit device timeout SHALL produce exit 124, `hermes_timed_out: true`, retained partial output and core's timeout suffix for the requested duration, just as a gateway timeout does. Bounded capture and spill metadata MUST remain intact. Gateway rendering SHALL remain bounded by the caller's deadline even if a device policy stops execution earlier.

#### Scenario: Device reports first
- **WHEN** an authenticated device timeout result reaches the gateway before its deadline
- **THEN** the gateway uses core's timeout rendering by the caller's deadline, not a normal-exit rendering
- **AND** nonempty partial output precedes exactly one timeout suffix

#### Scenario: Empty timed-out output
- **WHEN** the device reports a timeout without command output
- **THEN** the result has the same leading-whitespace behavior as core's own empty timeout result

#### Scenario: Timeout after output cap
- **WHEN** the command both exceeds its device output cap and times out
- **THEN** the timeout identity remains intact and the result also reports the configured output cap

### Requirement: Other terminal outcomes retain their identity
An ordinary exit 124, device loss, cancellation or policy refusal MUST NOT become a command timeout merely because its exit code or output resembles one. Existing notices and terminal-state arbitration SHALL remain unchanged.

#### Scenario: Command exits with 124
- **WHEN** a command exits with status 124 without a device timeout report
- **THEN** the result has no timeout suffix or `hermes_timed_out` flag

#### Scenario: Lost or cancelled command
- **WHEN** a command is marked lost or cancelled instead of reporting a finished timeout
- **THEN** its existing terminal state and rendering remain distinct from a command timeout
