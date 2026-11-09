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
