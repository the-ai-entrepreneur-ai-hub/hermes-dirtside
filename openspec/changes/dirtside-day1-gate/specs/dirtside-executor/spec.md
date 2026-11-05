# Spec Delta

## Purpose

Execute the exact core script on a POSIX device with bounded resources and local-compatible background process behavior.

## ADDED Requirements

### Requirement: Policy before spawn
The executor MUST reject a model command matching a compiled deny pattern before spawning, with refused state and exit code 126. It MUST inspect the model command, not the wrapped script, and MUST NOT claim folder confinement.

#### Scenario: Deny table
- **WHEN** a deny pattern matches the model command but not necessarily the script
- **THEN** execution is refused
- **AND** a pattern found only in a bootstrap script does not refuse an allowed command

### Requirement: Exact shell and asynchronous stdin
The executor MUST run the supplied script through bash with the supplied login flag, cwd and a new process group. A separate writer MUST deliver stdin as UTF-8 bytes while merged stdout and stderr drain concurrently.

#### Scenario: Full pipes
- **WHEN** a process writes more than a pipe buffer before reading a one megabyte stdin payload
- **THEN** execution completes without a deadlock and both streams remain byte-exact

### Requirement: Ordered flush and inline tail
Output MUST flush serially at 65536 bytes or 200 milliseconds after the first unsent byte. A final part of at most 65536 bytes MUST be returned with the outcome for an inline result. Output beyond the policy byte cap MUST be discarded with truncation reported.

#### Scenario: Short command
- **WHEN** echo finishes inside 200 milliseconds
- **THEN** its output travels only in the final result

#### Scenario: Slow command
- **WHEN** a command prints output and continues running beyond the flush interval
- **THEN** that output is sent before command completion

### Requirement: Timeout and cancellation kill the group
The executor MUST enforce the lesser of request and policy timeouts. Timeout, cancellation or a rejected output post MUST terminate the process group with SIGTERM and escalate to SIGKILL within three seconds, including children that ignore SIGTERM.

#### Scenario: Cancel running work
- **WHEN** cancellation arrives while bash and its child are running
- **THEN** the process group is dead within five seconds

### Requirement: Natural exit preserves grandchildren
After bash exits naturally, the executor MUST stop draining after about 300 milliseconds of pipe inactivity and MUST NOT terminate the process group.

#### Scenario: Background grandchild
- **WHEN** sleep is backgrounded for 30 seconds and bash exits
- **THEN** the tool returns in under one second and sleep remains alive

### Requirement: Signed in-process device
The test device MUST sign and verify poll, execution, chunk and result traffic using the shared protocol and MUST pass typed values into the relay. It MUST enforce a bounded number of parallel executions without opening a listening socket.

#### Scenario: Loopback round trip
- **WHEN** core sends a shell or file operation through the in-process device
- **THEN** both directions verify signatures and the real executor supplies the result
