## ADDED Requirements

### Requirement: Public target state
Runtime code MUST import nothing from tools.terminal_tool and MUST own per-target cwd and snapshots.

#### Scenario: test_no_terminal_internals
- **WHEN** target dispatch executes with private terminal imports blocked
- **THEN** cwd and exports work without touching core's cwd table

### Requirement: Stable target round trips
Targets MUST restore their own cwd and exports across repeated switches, including when task ids differ from session keys.

#### Scenario: test_gateway_target_roundtrips
- **WHEN** a gateway conversation makes three device/server/device round trips
- **THEN** each target restores its own directory and exported values

### Requirement: Idle continuity
A switch immediately after core idle cleanup MUST preserve saved target cwds.

#### Scenario: test_switch_after_idle_cleanup
- **WHEN** core reaps the facade then the target changes
- **THEN** a recreated facade starts in that target's saved directory

### Requirement: Core local control
Server execution MUST use the built-in local backend and MUST retain credential stripping.

#### Scenario: test_server_environment_control
- **WHEN** fake provider keys are planted in server execution and plain core local
- **THEN** both terminal paths omit them

### Requirement: Day-9 compatibility
All existing day-9 requirements MUST pass without editing their tests.

#### Scenario: test_target_switch_restores_cwd_and_exports
- **WHEN** the unedited day-9 battery runs in both transports
- **THEN** cwd, exports, failures, transient workdir, file-first switching and bounded history retain their assertions
