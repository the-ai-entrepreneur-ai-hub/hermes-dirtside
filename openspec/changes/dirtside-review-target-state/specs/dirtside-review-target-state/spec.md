## ADDED Requirements

### Requirement: Public target state
Runtime code MUST import nothing from tools.terminal_tool and MUST own per-target cwd and snapshots.

#### Scenario: test_no_terminal_internals
- **WHEN** runtime imports are inspected
- **THEN** no module imports tools.terminal_tool

#### Scenario: test_creation_and_selection_never_call_core_cwd_helpers
- **WHEN** creation and target selection run with private cwd helpers refusing calls
- **THEN** server and device execution succeed without those helpers

#### Scenario: test_history_comes_from_live_delegate_not_mutable_core_table
- **WHEN** the unrelated core record changes between target switches
- **THEN** saved cwd follows the live delegate and the plugin leaves that record untouched

#### Scenario: test_direct_cwd_argument_remains_explicit
- **WHEN** a direct environment caller supplies cwd without tool middleware
- **THEN** execution honors it normally

### Requirement: Declared public execution middleware
The plugin MUST declare its tool_execution middleware in the manifest.

#### Scenario: test_execution_middleware_matches_manifest
- **WHEN** core probes the plugin's registered capabilities
- **THEN** the registered middleware and manifest both contain exactly tool_execution

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
