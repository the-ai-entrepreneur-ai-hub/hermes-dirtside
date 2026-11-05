# Spec Delta

## Purpose

Ensure a normal enabled installation works through Hermes startup, terminal and file tools, and the authenticated dashboard.

## ADDED Requirements

### Requirement: Enabled directory installation
An installed and enabled plugin SHALL register its terminal backend, device authenticator and CLI family through normal startup discovery.

#### Scenario: Installed plugin is discovered
- **WHEN** the user installs the directory under the selected home's plugins directory and enables dirtside
- **THEN** startup discovers those registrations and plugin list and doctor recognize the installation

### Requirement: Tool conformance through the selected backend
The selected device SHALL preserve the normal terminal and file tool results, including persistent cwd, exports, nonzero exit codes and lossless file content.

#### Scenario: Normal tools run on a paired subprocess device
- **WHEN** the user chooses a paired online device and invokes terminal and file tools
- **THEN** pwd, separate cd and export calls, exit 3, 1 MB output, a 100 KB write and read, patch and search agree with the local backend after nondeterministic metadata is excluded

#### Scenario: The cached device becomes offline
- **WHEN** the device stops and the offline window elapses after earlier successful tool calls
- **THEN** the next terminal call reports the offline device and no command runs on the server

#### Scenario: No device selected
- **WHEN** the backend is dirtside with the server default and no conversation target
- **THEN** terminal executes locally and preserves cwd across calls

### Requirement: Dashboard credential separation
Device routes SHALL accept recognized device credentials without a dashboard session and reject unknown credentials. Desktop routes SHALL require a dashboard session.

#### Scenario: Real dashboard gate is active
- **WHEN** device and desktop requests reach the discovered plugin routes with the gate enabled on loopback
- **THEN** all four device paths enforce their device credentials and all desktop operations reject unauthenticated callers with 401

#### Scenario: Pane reflects execution
- **WHEN** a request runs on a paired device
- **THEN** devices, selected target and recent requests expose the documented pane fields, including online state, command preview, request state and live tail
