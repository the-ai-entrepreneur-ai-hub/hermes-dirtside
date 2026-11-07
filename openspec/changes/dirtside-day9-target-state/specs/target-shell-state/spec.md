# Spec Delta

## Purpose

Keep each target's shell state independent within a conversation so changing devices cannot replay another machine's working directory or exports.

## ADDED Requirements

### Requirement: Target-scoped shell state
A conversation SHALL retain a separate working directory and exported-variable snapshot for each resolved target. A newly visited device MUST start in its own home without another target's exports. Returning to a target MUST restore its previous state.

#### Scenario: Switch between devices
- **GIVEN** a conversation changed directory and exported X=1 on device A
- **WHEN** it selects device B and runs a command
- **THEN** the command succeeds in B's home and X is unset
- **WHEN** it selects A again
- **THEN** A's previous directory and X=1 are restored

#### Scenario: Conversation boundaries
- **GIVEN** one conversation changed directory and exported a variable on a device
- **WHEN** another conversation selects that device
- **THEN** the second conversation starts with its own shell state

#### Scenario: Recreated facade on the same device
- **GIVEN** device A has a tracked directory and core reaps its idle facade
- **WHEN** the next operation uses A again
- **THEN** the surviving core cwd record is not overwritten and A uses its tracked directory

#### Scenario: Target changes during facade eviction
- **GIVEN** A has a tracked directory and its facade is reaped
- **WHEN** the conversation selects server or another device before recreation
- **THEN** the next operation uses that target's own directory, not A's

### Requirement: Bounded transition history
Transition identity and saved cwds SHALL live on the provider independently of facade lifetime, with a maximum of 1,024 least-recently-used conversation entries. A visit MUST refresh recency; adding an entry beyond the cap MUST remove the least recently used entry.

#### Scenario: History reaches its cap
- **GIVEN** 1,024 conversations have transition history
- **WHEN** one old conversation is revisited and a new conversation is added
- **THEN** the revisited entry remains and the least recently used entry is removed

#### Scenario: A live delegate outlasts history
- **GIVEN** a target's live delegate has changed directory and its conversation history is evicted
- **WHEN** that target is selected again
- **THEN** its live directory is recorded instead of the reconstructed seed

### Requirement: Independent conversation bootstrap
Delegate bootstrap SHALL NOT hold the provider-wide transition lock. A conversation waiting for device bootstrap MUST NOT prevent another facade's server command or metadata selection from completing.

#### Scenario: Device bootstrap waits
- **GIVEN** one conversation's device bootstrap is blocked
- **WHEN** another conversation reads its cwd and provider defaults and executes on server
- **THEN** those operations complete before the blocked bootstrap is released

### Requirement: Safe optional capability lookup
Optional lookup of the facade's temp-directory method SHALL NOT resolve a target. Calling it MAY raise the existing connection error, which core's temp-directory callers handle.

#### Scenario: Oversized result while a selected device is offline
- **GIVEN** a live facade selects an offline device without a delegate
- **WHEN** core looks up its temp-directory method and resolves result storage
- **THEN** lookup succeeds and storage resolution falls back without raising
- **WHEN** an oversized non-terminal tool result cannot be saved to the device
- **THEN** core returns its inline-truncation fallback

### Requirement: Bootstrap requires contact
A device delegate MUST NOT be constructed before online contact, including selection through metadata. A failed offline command MUST NOT prevent later commands from retaining exports after the agent starts.

#### Scenario: Selected before agent startup
- **GIVEN** a paired device is selected while offline
- **WHEN** a command runs
- **THEN** the existing offline result is returned without server execution
- **WHEN** its agent starts and separate export and read commands run
- **THEN** the exported value is retained

### Requirement: Safe cwd metadata
The cwd getter SHALL return the last known directory rather than raise a connection error when selection is offline or revoked; execution MUST remain fail-closed.

#### Scenario: Unavailable selection is inspected
- **GIVEN** a live facade has a known directory
- **WHEN** an offline or revoked selection is inspected through its cwd getter
- **THEN** metadata reads return the known directory without running a command

### Requirement: Server state remains local
The server target SHALL retain core's local shell behavior and its own state across device switches. Explicit per-command workdirs MUST retain core's existing semantics.

#### Scenario: Server between devices
- **GIVEN** a conversation has shell state on device A
- **WHEN** it selects server, changes directory and exports a different value, then selects device B
- **THEN** B starts at its own home without A's or server's exports
- **WHEN** it returns to server and then A
- **THEN** each target restores only its own directory and exported value

#### Scenario: Transient workdir
- **GIVEN** a conversation has a persistent directory on server
- **WHEN** it runs a command with an explicit transient workdir and later switches away and back
- **THEN** server retains the persistent directory according to core's local behavior

### Requirement: No cross-target directory replay
A target switch MUST NOT replay another target's tracked directory. A directory deleted from the current target MUST retain core's existing failure status and rendering rather than silently reset to home.

#### Scenario: Directory unavailable on the next device
- **GIVEN** A's tracked directory does not exist on B
- **WHEN** the conversation switches from A to B
- **THEN** B's next command succeeds without attempting to enter A's directory

#### Scenario: Current directory was deleted
- **GIVEN** the current target's tracked directory was deleted
- **WHEN** another command runs on that target
- **THEN** the existing directory failure is returned without a fallback execution at home

### Requirement: Transport-independent conformance
Target switching SHALL obey the same shell-state rules through in-process and client transports, using core's real terminal entry point without editing or rebinding core.

#### Scenario: Both dispatch paths
- **WHEN** the target-switch conformance cases run through each transport
- **THEN** their output, status and working-directory assertions all pass
