## ADDED Requirements

### Requirement: per turn target facts

The plugin SHALL provide the behavior below without changing core, protocol version 1 or the base authorization rules.

#### Scenario: test_absolute_file_tools_land_on_device
- **WHEN** real core read, write, patch and search use absolute paths without gateway-side symlinks in a different device home on the shared disk
- **THEN** device bytes change and the corresponding server home stays untouched, without claiming separate-disk correctness

#### Scenario: test_next_turn_target_facts_and_authority
- **WHEN** a turn follows device selection, /orbit, explicit server selection or an unauthorized sender
- **THEN** an authorized device yields bounded facts, explicit server selection yields the fixed server fact, and an untouched server-default conversation or unauthorized device yields nothing

#### Scenario: test_fact_line_matches_gateway_path_resolution
- **WHEN** the device home either survives gateway resolution or contains a gateway-side symlink
- **THEN** the bounded line forbids tilde and recommends absolute paths in the first case, or directs edits and extractable document reads through terminal commands with absolute plain-text reads/searches in the second, and says Android API commands are untested

#### Scenario: test_fact_hook_fails_open_without_contact
- **WHEN** state fails or the relay cannot be contacted
- **THEN** the hook never raises and performs no contact

#### Scenario: test_tilde_write_uses_gateway_home_known_limit
- **WHEN** real core file tools receive ~/name with different homes
- **THEN** write_file executes on the device at a gateway-home-shaped path while read_file uses the device home, with this visible result depending on the shared disk

#### Scenario: test_gateway_symlink_write_and_patch_resolve_before_signed_device_request_known_limit
- **WHEN** write_file and patch receive an absolute path under a gateway-side symlinked prefix
- **THEN** the device receives the gateway-resolved path after poll signature verification, documenting the known cross-filesystem limit

#### Scenario: test_config_warning_in_real_selection_and_hook
- **WHEN** real slash dispatch selects a device with local, dirtside, missing, empty or non-string backend configuration, a missing setting with a dirtside/docker process fallback, or a file made unreadable after startup bridged dirtside
- **THEN** local keeps its configured-backend sentence, missing and empty use stripped TERMINAL_ENV or local and warn unless it is dirtside, both selection spellings and the hook share that warning, non-string and already-bridged unreadable cases keep their original replies and facts, and server selection never warns

#### Scenario: test_config_warning_quotes_and_bounds_value
- **WHEN** configuration or the process fallback names another backend containing a long value and line breaks
- **THEN** the warning quotes and bounds the value, remains one line within 600 characters and gives no device facts

#### Scenario: test_empty_file_result_warns_default_backend
- **WHEN** the real read-only reader returns an empty mapping for a missing or unparseable file and TERMINAL_ENV is absent
- **THEN** the hook warns that the backend is local because terminal.backend is not set, without device facts

#### Scenario: test_frozen_prompt_uses_authorized_backend_warning
- **WHEN** real prompt rendering resolves an authorized saved or configured-default device with configured or fallback backends, including missing and empty settings, and with non-string or already-bridged unreadable configuration
- **THEN** non-dirtside strings replace facts with the appropriate shared warning, dirtside, non-string and already-bridged unreadable cases keep their original results, and unauthorized or server targets disclose no new device facts or backend warning

#### Scenario: test_unreadable_reader_keeps_existing_facts
- **WHEN** the public read-only reader reports unreadability through an exception or SystemExit
- **THEN** selection is not gated and the hook keeps its existing device facts without a configuration warning

#### Scenario: test_offline_hint_names_both_device_entrypoints
- **WHEN** an offline device cannot run a command
- **THEN** the retry hint names both dirtside-agent serve and hermes dirtside serve, as well as explicit server selection

#### Scenario: test_readme_command_replies_and_device_entrypoints
- **WHEN** the README sample is compared with the actual pair/use handlers and the device quick-start steps are read
- **THEN** both replies match, both device command forms appear, and each Hermes form requires the plugin installed and enabled on that device
