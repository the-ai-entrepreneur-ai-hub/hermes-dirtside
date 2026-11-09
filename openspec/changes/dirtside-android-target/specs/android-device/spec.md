## ADDED Requirements

### Requirement: android device

The plugin SHALL provide the behavior below without changing core, protocol version 1 or the base authorization rules.

#### Scenario: test_termux_detection_and_environment
- **WHEN** a real-shaped Termux environment is present
- **THEN** OS is Android (Termux), measured system names merge and explicit passthrough remains

#### Scenario: test_other_platform_environment_unchanged
- **WHEN** Termux markers are absent
- **THEN** the exact base environment allowlist remains

#### Scenario: test_termux_default_names_exclude_secrets
- **WHEN** secret-shaped variables appear beside Termux system names
- **THEN** no KEY, TOKEN, SECRET, PASSWORD or AUTH shaped default is admitted

#### Scenario: test_pairing_reports_termux
- **WHEN** the pairing CLI runs under Termux
- **THEN** the signed hello reports Android (Termux) in the existing os field

#### Scenario: test_termux_loopback_forward
- **WHEN** a signed HTTP body crosses the container-loopback forward
- **THEN** body bytes, authorization, response status and response bytes are preserved

#### Scenario: test_termux_signed_path
- **WHEN** the real Termux Docker image runs through the rig
- **THEN** shebang, python3, PREFIX, nonzero exit, cancellation and revoke work; the full container scenario is owner-run and is not claimed by the builder
