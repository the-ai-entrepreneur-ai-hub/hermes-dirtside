# Spec Delta

## Purpose

Expose device health, conversation targeting and recent execution output in an optional native Desktop pane.

## ADDED Requirements

### Requirement: Device and request pane
The pane SHALL list each paired device's name, online state, OS, home and last seen with a revoke action. It SHALL show recent request previews, device, state, exit code and live output tail. Device and request reads SHALL poll every two seconds while visible and stop when hidden.

#### Scenario: Visible live request
- **WHEN** the pane is visible and a request is running
- **THEN** polling displays its current state and the returned output tail
- **AND** output is rendered as text, never HTML

#### Scenario: Hidden pane or unavailable backend
- **WHEN** the pane is hidden
- **THEN** device and request polling stops
- **AND** an unavailable backend displays an error rather than fabricated devices or success

### Requirement: Focused conversation controls
The pane SHALL display the focused conversation's target and persist picker changes through its target endpoint. A status chip SHALL show that same target. Writes SHALL require a resolved conversation identity on the REST helper's active owner route.

#### Scenario: Pick server over a device default
- **WHEN** a user chooses server for the focused conversation
- **THEN** the PUT persists explicit server and both pane and chip refresh from server truth
- **AND** the UI states that the change applies from the next command

#### Scenario: Switch conversations or connections
- **WHEN** focus or gateway ownership changes during an asynchronous read
- **THEN** the old result cannot populate the new conversation's target
- **AND** a missing or foreign owner disables target writes

### Requirement: Uncompiled unified delivery
The Desktop half SHALL load as a plain JavaScript ES module from the unified package without a build step, dashboard UI bundle or plugin events.

#### Scenario: Module syntax validation
- **WHEN** Node is available during tests
- **THEN** module-mode syntax checking succeeds
- **AND** absence of Node skips only that check
