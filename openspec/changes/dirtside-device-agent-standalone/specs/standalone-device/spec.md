## ADDED Requirements

### Requirement: service state preserves the override

Existing Hermes service rendering SHALL keep the selected Hermes profile and an absolute DIRTSIDE_HOME override, without changing standalone service availability.

#### Scenario: test_legacy_service_keeps_override_and_profile
- **WHEN** a user renders a legacy Hermes service with DIRTSIDE_HOME set
- **THEN** launchd and systemd retain both state roots and put service logs beside device.json without writing anything in dry-run mode

### Requirement: test homes do not inherit device state

The test entry point and owned core rig SHALL discard an outer DIRTSIDE_HOME when creating isolated homes.

#### Scenario: test_isolated_homes_ignore_state_override
- **WHEN** a test starts with an outer device-state override
- **THEN** pairing uses only its owned rig home, the outer pairing file is unchanged and pytest collection discards the inherited override

### Requirement: standalone device

The plugin SHALL provide the behavior below without changing core, protocol version 1 or the base authorization rules.

#### Scenario: test_device_imports_without_core
- **WHEN** the device imports run while all gateway namespaces are blocked
- **THEN** all four device imports succeed without loading Hermes

#### Scenario: test_state_location_order_and_legacy_pairing
- **WHEN** state is located with an override, an importable core or neither
- **THEN** override wins, an old pairing loads unchanged, otherwise ~/.dirtside is used

#### Scenario: test_relative_state_resolves_before_service_changes_directory
- **WHEN** a relative DIRTSIDE_HOME is resolved while writing device state and its generated absolute service environment is used by a fresh console process from another directory
- **THEN** lookup returns an absolute device.json path and the new process reads the unchanged pairing without creating state under its new directory

#### Scenario: test_unknown_home_user_reports_one_line
- **WHEN** status, serve, policy or pair expands a DIRTSIDE_HOME with an unknown tilde user
- **THEN** the console exits one with the usual single-line command error and no traceback

#### Scenario: test_standalone_install_signed_terminal_and_revoke
- **WHEN** a clean local install pairs and serves via the real rig
- **THEN** no Hermes package is installed, the actual terminal returns device output and revoke stops the agent

#### Scenario: test_home_dotenv_is_not_loaded
- **WHEN** the explicit/default Hermes homes and installed project root contain a fake provider key in .env
- **THEN** the real serving console process itself never acquires that name, and the check rejects temporary load_dotenv mutations for the home and project locations

#### Scenario: test_console_and_pairing_guidance
- **WHEN** either CLI pairs or displays help
- **THEN** guidance names the invoked command, both forms are offered, standalone has no service action

#### Scenario: test_pipx_local_install
- **WHEN** pipx installs the local package into isolated directories
- **THEN** dirtside-agent runs without Hermes
