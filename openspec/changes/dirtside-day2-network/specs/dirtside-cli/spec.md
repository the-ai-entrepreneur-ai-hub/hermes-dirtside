# Spec Delta

## Purpose

Pair and run a personal device from its own Hermes installation while keeping credentials private and exposing a local operational status.

## ADDED Requirements

### Requirement: Private device configuration
Device configuration SHALL be atomically saved with mode 0600 at the selected Hermes home's dirtside/device.json, containing only gateway URL, device identity, token, seed, pinned relay key, name and policy.

#### Scenario: Configuration round trip
- **WHEN** a valid configuration is saved and loaded in an isolated Hermes home
- **THEN** identity, keys and compiled policy agree and the file mode is 0600

#### Scenario: Unsafe configuration
- **WHEN** keys are invalid, policy caps are nonpositive or a remote gateway URL uses plain HTTP
- **THEN** configuration is rejected without starting execution

### Requirement: Pair and serve commands
The CLI SHALL support `hermes dirtside pair <gateway-url> --name <name> --code=<code>` and `hermes dirtside serve`. Pair SHALL send a signed hello, save the returned identity and pinned key, and never print the long-lived token.

#### Scenario: CLI pairing
- **WHEN** pair is invoked with a minted code
- **THEN** the private configuration is saved and serve can use it without more credentials

#### Scenario: Subprocess entry
- **WHEN** `python -m dirtside.agent` runs with saved configuration
- **THEN** it starts the same foreground agent and honors process signals

### Requirement: Local status
Status SHALL report the paired gateway, online or offline contact, policy caps and recent request log lines without claiming work or exposing credentials.

#### Scenario: Status after work
- **WHEN** status runs after the agent has completed a request
- **THEN** it displays pairing and recent request information without posting a device poll
