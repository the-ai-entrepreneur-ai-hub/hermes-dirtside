## ADDED Requirements

### Requirement: Exact transitional surface
Core's private-import lint on a clean export MUST report exactly one token_auth fallback, one LocalEnvironment fallback and one EnvironmentConnectionError import.

#### Scenario: test_private_imports_are_exact_transitional_set
- **WHEN** either core validates the exported plugin tree
- **THEN** only the three disclosed transitional sites are found

### Requirement: Honest development layout
Non-runtime modules importing core internals MUST live under tests and documented commands MUST remain runnable.

#### Scenario: test_development_entrypoints
- **WHEN** CI, benchmark and matrix entry points load after relocation
- **THEN** they load their helpers without production re-export shims or non-test test_ files

### Requirement: Documented limits
Documentation MUST disclose ownership, device policy and all remaining private seams, and its test count MUST match collection.

#### Scenario: test_review_documentation
- **WHEN** the owner reads commands, security and status
- **THEN** rules match tested behavior and no catalog-unblocked claim is made

### Requirement: Explicit shared-session and host-execution limits
README MUST state what the frozen target section reveals and that server execution can recover the local credential and act as local.

#### Scenario: test_frozen_group_prompt_disclosure_matches_core
- **WHEN** two senders share the real core's frozen prompt snapshot
- **THEN** the second receives the first target facts, device dispatch still refuses, and documentation names the exposed fields

#### Scenario: test_server_execution_limit_is_explicit
- **WHEN** a sender runs server-target commands as the gateway user
- **THEN** the temporary local secret permits local IPC and README points to core approvals and allowlists rather than claiming isolation

### Requirement: Correction 2 verification evidence
Correction 2 MUST record behavioral red/green evidence, both full core suites, pinned fast, static checks, strict OpenSpec, both doctors and clean native validators with exactly three private import sites, matrix 8/8, strict benchmark and five serial repeats of the C1/C2 changed test-file union.

#### Scenario: correction_2_final_gates
- **WHEN** the final intended source is verified
- **THEN** exact outputs, failures, budget changes, inventories since C1 and WP5, cumulative checkpoints and remaining limits appear in the private report

### Requirement: Correction 3 verification evidence
Correction 3 MUST prove native CLI/TUI local identity red and green on both prepared cores, clean up every process its tests start, and rerun every requested final gate plus five serial whole-file repeats of all C1-C3 changed tests and helpers without relaxing a bound.

#### Scenario: test_core_owner_loss_midstream_has_no_timeout_hint
- **WHEN** the owner-loss test runs with a persistent cwd different from its fixture work directory
- **THEN** its bash loop is stopped by the test teardown and no descendant remains

#### Scenario: correction_3_final_gates
- **WHEN** the final intended source is checked
- **THEN** the report includes exact red/green and final-gate outputs, both-core admission with three private sites, inventories since C2 and WP5, reconstructed C3 checkpoints and an explicit optional-optimization decision

### Requirement: Accurate correction 4 operator guidance
README and architecture MUST disclose actual core login authority, unsupported Windows host subjects, safe pairing syntax and gateway-side file-path resolution. Core citations MUST NOT resemble repository-local file-and-line references.

#### Scenario: test_core_login_and_device_limits_are_explicit
- **WHEN** the reader follows either operator guide
- **THEN** dashboard/Webapp/forwarded sign-ins act as host, Windows SID host support is absent, pairing uses the equals form and the file-path limit is stated

#### Scenario: test_core_citations_do_not_look_repository_local
- **WHEN** all repository markdown is checked and the unchanged owner citation checker runs
- **THEN** core citations use explicit core filenames and prose line references, and the actual checker passes

### Requirement: Correction 4 verification evidence
Correction 4 MUST retain red/green evidence, all prior final gates, five whole-file correction rounds and 20 serial loaded client reload cases on each prepared core, with no owned process left running.

#### Scenario: correction_4_final_gates
- **WHEN** the final intended source is delivered uncommitted
- **THEN** exact outputs, all failed attempts, budgets, reconstructed C4 checkpoints, inventories since C3 and WP5, cleanup and remaining limits appear in the appended private report
