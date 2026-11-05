# Spec Delta

## Purpose

Let users inspect and choose a conversation's execution target, pair devices and revoke their access from chat.

## ADDED Requirements

### Requirement: Conversation target precedence
An explicit server or device selection SHALL override the default for that conversation. No selection SHALL use the configured default, except cron SHALL default to server. A removed or offline explicitly selected device SHALL fail closed.

#### Scenario: Explicit server over a device default
- **WHEN** macbook is the configured default and a conversation selects server
- **THEN** its next command runs on the server, including when an environment was already cached
- **AND** another conversation's target is unchanged

#### Scenario: Selected device is revoked
- **WHEN** a conversation's selected device is no longer paired
- **THEN** its next command fails without executing on the server

#### Scenario: Existing target database
- **WHEN** an older database containing device selections is opened
- **THEN** selections and timestamps survive migration
- **AND** deleting a selection restores the configured default

### Requirement: Inspect and select targets in chat
The command SHALL report the target and online devices, list paired devices with online state, and accept `use <name|server>`. Bare `use` SHALL offer online devices plus server. A successful change SHALL state that it applies to this conversation from the next command. Invalid or cancelled input SHALL not change the target.

#### Scenario: Online picker and offline named choice
- **WHEN** the user invokes bare use
- **THEN** only online devices and server are offered
- **AND** an explicitly named paired offline device remains selectable with its offline status stated

#### Scenario: No conversation identity
- **WHEN** a target change has no bound conversation
- **THEN** it is refused without writing a shared empty-key selection

### Requirement: Pair and revoke from chat
Pairing SHALL return a single-use code and an exact device-side pairing command with a gateway URL placeholder. Revocation SHALL invalidate the device credential and immediately cancel its live requests. Replies SHALL use one or two plain sentences.

#### Scenario: Pair a named device
- **WHEN** a valid name is supplied to pair
- **THEN** a code expiring in ten minutes and `hermes dirtside pair <gateway-url> --name <name> --code=<code>` are returned

#### Scenario: Revoke active work
- **WHEN** a paired device with a live request is revoked
- **THEN** the waiting request returns cancellation and the device's credential stops working
