## ADDED Requirements

### Requirement: Owner controls
Local, device owners and configured owners MUST be the only senders who use or manage an existing device; all listings and pickers MUST be filtered.

#### Scenario: test_owner_commands
- **WHEN** A pairs a laptop and B tries commands and listings
- **THEN** B cannot see or manage it while A, local and configured owners can

### Requirement: Pairing authority
With a nonempty owners list only local and listed senders MUST pair new names; with an empty list another admitted sender MAY pair and MUST own that name.

#### Scenario: test_pairing_authority
- **WHEN** the owners list is empty or populated
- **THEN** minting follows the rule and pending completion binds the minting sender

#### Scenario: test_native_sender_spelling_can_own_device
- **WHEN** an admitted email address, Signal phone number or IRC nick pairs a device
- **THEN** its exact public sender identity owns the device and another sender cannot discover it

### Requirement: Dispatch authority
An explicit device target MUST be authorized against the current turn sender in both transports and MUST never fall back to the server.

#### Scenario: test_group_dispatch
- **WHEN** B makes terminal or file calls after A selects a device in the same group session
- **THEN** no request reaches the device and no command runs on the server; A's next turn succeeds

### Requirement: Default authority
An inaccessible configured default MUST resolve to server for that sender and the prompt MUST say server.

#### Scenario: test_owned_default
- **WHEN** A and B have separate unselected conversations
- **THEN** A resolves to the device and B resolves to server

### Requirement: Compatible registry migration
Opening an old registry MUST preserve devices, targets and requests, default old owners to local, and be idempotent.

#### Scenario: test_old_registry_migration
- **WHEN** a registry produced by 0ae9359's own code is opened twice
- **THEN** its records survive with local ownership

### Requirement: Unspoofable local identity
A messaging id local or a platform looking like cli MUST NOT become local; cron behavior MUST remain unchanged.

#### Scenario: test_sender_provenance
- **WHEN** remote identity strings resemble host surfaces or a cron turn runs
- **THEN** remote authority stays remote and cron keeps its existing target behavior
