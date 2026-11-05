# Spec Delta

## Purpose

Resolve the conversation's execution target while retaining local behavior for server-target sessions.

## ADDED Requirements

### Requirement: Target precedence
An explicit conversation device identifier MUST take precedence over the configured default. Without an explicit choice, cron MUST use the server. Other conversations MUST use a paired default device when configured, or the server otherwise.

#### Scenario: Six-row target table
- **WHEN** resolution receives the six cases below
- **THEN** it returns the stated target or connection error

| Choice | Cron | Default | Device online | Result |
|---|---|---|---|---|
| none | no | server | not applicable | server |
| none | yes | paired device | yes | server |
| none | no | paired device | yes | default device |
| chosen device | yes | server | yes | chosen device |
| chosen device | no | another device | yes | chosen device |
| chosen device | no | server | no | connection error |

#### Scenario: Revoked choice
- **WHEN** an explicit conversation device is no longer paired
- **THEN** resolution raises a connection error instead of choosing the server

### Requirement: Offline devices fail closed
An offline selected device MUST raise a connection error with recovery instructions before constructing any execution environment. It MUST NOT execute the command on the server.

#### Scenario: Offline execution
- **WHEN** environment creation targets an offline device
- **THEN** creation fails without creating local state or running a server command

### Requirement: Server target preserves core local behavior
A server target MUST use core's local environment, with literal `~` translated to its normal initial cwd. Device-provider flags MUST keep dangerous-command approvals enabled.

#### Scenario: No device selected
- **WHEN** no device is selected and the default is server
- **THEN** pwd, cd and the following pwd behave exactly as core's local backend

### Requirement: Stable conversation identity
Resolution MUST use the bound session key, falling back to the bound session identifier for surfaces without a key. An absent identity MUST NOT share a mutable device selection with another unbound caller.

#### Scenario: Session identifier fallback
- **WHEN** the session key is empty and a session identifier is bound
- **THEN** the session identifier names the target lookup

#### Scenario: No bound identity
- **WHEN** neither key nor identifier is available
- **THEN** only the default target is considered, with no shared empty-key selection
