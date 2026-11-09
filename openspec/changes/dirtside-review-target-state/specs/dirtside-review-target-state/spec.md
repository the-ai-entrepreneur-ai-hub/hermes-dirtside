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

### Requirement: Context-free snapshot cleanup
Plugin cleanup MUST remove only its own snapshot and temporary snapshot fragments without requiring a turn context or running a model command.

#### Scenario: test_context_free_cleanup_removes_only_its_snapshot
- **WHEN** core reaps or shuts down an environment in an empty-context thread
- **THEN** its snapshot artifacts disappear, unrelated files remain, the cleanup preview is empty, and a model command in that thread still refuses

### Requirement: Conversation default snapshot
A non-cron conversation MUST snapshot its configured default name at its first target resolution and retain it through reload and environment recreation. New conversations MUST use the new configured default. Explicit choices MUST remain live and authorization MUST remain per turn.

#### Scenario: test_default_snapshot_survives_reload
- **WHEN** a real conversation resolves its prompt or runs its first command before default configuration changes
- **THEN** its cached or recreated environment keeps the original default, its frozen prompt is unchanged, and a new conversation uses the new default

#### Scenario: test_default_snapshot_is_shared_with_independent_registry
- **WHEN** independent registry instances resolve one conversation under different configured defaults and later clear an explicit choice
- **THEN** they share its first captured name and clearing restores that captured default

#### Scenario: test_cron_does_not_snapshot_an_interactive_default
- **WHEN** cron resolves before the same key is used interactively
- **THEN** cron does not capture a default, keeps its server behavior and still honors an explicit device

### Requirement: Local Desktop target resolution
Desktop target GET MUST use the dispatch resolver with local authority and MUST NOT display an untrusted implicit device when dispatch resolves server.

#### Scenario: test_desktop_default_uses_local_trust_rule
- **WHEN** another sender owns the configured implicit device name
- **THEN** target GET reports server until local explicitly selects that device

### Requirement: Honest device file-path guidance
Documentation MUST promise chosen-machine terminal commands without promising device-side file-path resolution.

#### Scenario: test_readme_promises_terminal_not_device_file_path_resolution
- **WHEN** the reader sees the headline, product description and earlier live-check list
- **THEN** terminal routing is the promise and the gateway-side file-path limitation is explicit
