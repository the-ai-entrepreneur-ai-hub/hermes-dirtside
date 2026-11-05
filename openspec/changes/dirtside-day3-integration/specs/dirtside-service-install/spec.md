# Spec Delta

## Purpose

Let a paired personal device keep its agent running through a per-user service without changing system-wide services.

## ADDED Requirements

### Requirement: Per-user persistent service
The install-service command SHALL install an idempotent per-user service running hermes dirtside serve, pin the installation home, and keep logs private.

#### Scenario: macOS installation
- **WHEN** the user installs the service on macOS
- **THEN** Library/LaunchAgents/ai.hermes.dirtside.plist contains KeepAlive and a private log path and the available launchd user manager loads it

#### Scenario: Linux installation
- **WHEN** the user installs the service on Linux
- **THEN** .config/systemd/user/hermes-dirtside.service contains Restart=always and the available systemd user manager enables it

#### Scenario: Repeat installation
- **WHEN** the same service is installed again
- **THEN** the unit remains unchanged and no duplicate service is created

### Requirement: Safe preview and reversal
Dry-run SHALL print the proposed service without any writes or manager calls. Remove SHALL undo the installed user service and be safe to repeat.

#### Scenario: Preview without configuration
- **WHEN** an unpaired user invokes install-service --dry-run
- **THEN** the service text is printed and no service files, logs or processes are created

#### Scenario: Repeated removal
- **WHEN** the user removes an installed service and repeats removal
- **THEN** the service file is absent and both removals succeed without affecting other services
