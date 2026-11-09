## ADDED Requirements

### Requirement: Owner controls
Local, device owners and configured owners MUST be the only senders who use or manage an existing device; all listings and pickers MUST be filtered.

#### Scenario: test_owner_commands
- **WHEN** A pairs a laptop and B tries commands and listings
- **THEN** B cannot see or manage it while A, local and configured owners can

#### Scenario: test_global_and_local_owners
- **WHEN** a listed global owner or the trusted local host manages another sender's device
- **THEN** discovery, selection, code minting and revocation retain their authority

### Requirement: Pairing authority
With a nonempty owners list only local and listed senders MUST pair new names; with an empty list another admitted sender MAY pair and MUST own that name.

#### Scenario: test_pairing_authority
- **WHEN** the owners list is empty or populated
- **THEN** minting follows the rule and pending completion binds the minting sender

#### Scenario: test_native_sender_spelling_can_own_device
- **WHEN** an admitted email address including a quoted local part with spaces, Signal phone number or IRC nick pairs a device
- **THEN** its exact public sender identity owns the device and another sender cannot discover it

#### Scenario: test_repair_transfers_pending_owner
- **WHEN** another sender pairs a revoked name using their own pending code
- **THEN** a fresh device id belongs to the minting sender and the previous id remains revoked

#### Scenario: test_pending_names_cannot_be_stolen
- **WHEN** B tries to mint or revoke A's pending name
- **THEN** A's pending code stays valid and B cannot acquire it

#### Scenario: test_concurrent_pairing_cannot_replace_another_sender
- **WHEN** two senders concurrently mint one new name
- **THEN** exactly one obtains a code and its owner remains the sole live row

### Requirement: Validated owner configuration
The optional owners list MUST have an empty manifest default, at most 64 unique bounded printable identities, and no control or formatting characters.

#### Scenario: test_bad_owners_refused
- **WHEN** owner configuration has a wrong type, malformed identity, duplicate or control character
- **THEN** it is refused with an owners error

#### Scenario: test_owner_list_bounds
- **WHEN** list length or native identity length reaches its exact bound and then exceeds it
- **THEN** only the bounded form is accepted

#### Scenario: test_owner_config_schema
- **WHEN** core reads the plugin manifest
- **THEN** owners is an optional list with an empty default

### Requirement: Dispatch authority
An explicit device target MUST be authorized against the current turn sender in both transports and MUST never fall back to the server.

#### Scenario: test_group_dispatch
- **WHEN** B makes terminal or file calls after A selects a device in the same group session
- **THEN** no request reaches the device and no command runs on the server; A's next turn succeeds

#### Scenario: test_owner_rechecks_worker_config
- **WHEN** a worker lists B as privileged but the independently configured serving owner does not
- **THEN** owner-side dispatch refuses without device work or request history

#### Scenario: test_local_sender_is_bounded_and_rechecked
- **WHEN** authenticated local IPC claims an empty or malformed sender
- **THEN** the owner returns 403 before creating work or history

### Requirement: Default authority
An implicit default MUST resolve to a device only when owned by the sender, local or a listed owner; otherwise it MUST resolve to server even for a privileged sender. The initial prompt MUST match that resolution.

#### Scenario: test_owned_default
- **WHEN** A and B have separate unselected conversations
- **THEN** A resolves to the device and B resolves to server

### Requirement: Compatible registry migration
Opening an old registry MUST preserve devices, targets and requests, default old owners to local, and be idempotent.

#### Scenario: test_old_registry_migration
- **WHEN** a registry produced by 0ae9359's own code is opened three times
- **THEN** its devices, targets, pending token, keys and queued/finished request rows survive with local ownership

### Requirement: Unspoofable local identity
A messaging id local or a platform looking like cli MUST NOT become local; cron behavior MUST remain unchanged.

#### Scenario: test_sender_provenance
- **WHEN** remote identity strings resemble host surfaces or a cron turn runs
- **THEN** remote authority stays remote and cron keeps its existing target behavior

#### Scenario: test_cron_keeps_host_authority_without_a_messaging_sender
- **WHEN** core binds a trusted cron turn without messaging routing
- **THEN** it retains local authority without guessing an unidentified remote sender is local

#### Scenario: test_canonical_local_actor_uses_real_core_policy
- **WHEN** a real LocalSessionPolicy binds CLI, TUI, Desktop or ACP with an empty or same-uid local subject, another uid or an arbitrary label
- **THEN** only the empty or exact same-uid subject identifies the trusted host as local

#### Scenario: test_local_platform_requires_same_uid
- **WHEN** core exposes platform local and surface local, CLI, TUI, Desktop or ACP
- **THEN** trusted policy surfaces accept only an empty user or the exact current uid subject, and policy-free surface local requires the additional command proof

#### Scenario: test_messaging_uid_cannot_become_local
- **WHEN** a messaging or CLI-looking remote platform carries local or the host uid as its user id
- **THEN** its identity remains platform-qualified even with a local-looking surface or source

#### Scenario: test_native_local_demo
- **WHEN** authenticated native CLI and TUI sessions use the ordinary daemon, core slash handlers, terminal turns and a local-owned device in temporary homes
- **THEN** status says Sender: local, the device is visible and usable, each target retains its cd/export state, device commands execute there, revocation closes selection and the next command fails without running on server

### Requirement: Name-squatting resistance
Implicit defaults MUST NOT grant unprivileged device owners the privileged sender's work; cross-owner re-pairing MUST NOT revive stale device ids.

#### Scenario: test_untrusted_implicit_default_uses_server
- **WHEN** a messaging sender pairs the configured default before local or a listed owner uses it
- **THEN** implicit work resolves server, explicit use remains possible, and sender-owned or privileged-owned defaults remain usable

#### Scenario: test_cross_owner_repair_keeps_stale_target_closed
- **WHEN** a different owner pairs a revoked name and an earlier owner later returns
- **THEN** each owner change creates a fresh id, stale targets fail closed, and immediate same-owner re-pair retains its id

#### Scenario: test_privileged_use_names_unprivileged_owner
- **WHEN** local or a listed owner explicitly selects an unprivileged owner's device
- **THEN** confirmation names the exact owner and ordinary owner or trusted-owner confirmations remain unchanged

#### Scenario: test_implicit_default_never_sends_operator_work_to_squatter
- **WHEN** a privileged conversation executes with an unprivileged-owned implicit default
- **THEN** it runs on the server and no request reaches the squatter

### Requirement: Honest pairing-name disclosure
Documentation MUST distinguish filtered discovery and missing-name use/revoke refusal from observable pairing availability.

#### Scenario: test_pairing_name_availability_disclosure
- **WHEN** a sender pairs an occupied foreign name and a free name
- **THEN** the first refuses, the second produces a code, and README explicitly discloses that difference

### Requirement: Immediate displaced-owner cancellation
Successful cross-owner pairing MUST cancel live requests for the displaced active device immediately, not wait for the device-loss timeout. Failed pairing MUST NOT cancel work.

#### Scenario: test_cross_owner_pairing_cancels_live_requests
- **WHEN** local completes a signed pairing over another owner's active name with queued and running work
- **THEN** the old token and id stay revoked, both handles are cancelled immediately, and the new id remains usable

### Requirement: Relay-safe command provenance
Policy-free surface local MUST require actual non-relay core command source in addition to the empty-or-same-POSIX-uid rule, and MUST NOT infer authority from chat/session id equality.

#### Scenario: test_relay_wire_local_cannot_become_host
- **WHEN** core decodes relay wire platform local with no user or the gateway uid, even with matching chat/session ids and a forged false relay flag
- **THEN** real session binding and command dispatch do not grant host identity or privileged pairing

#### Scenario: test_command_source_authority_is_scoped
- **WHEN** an actual native source invokes a policy-free local command with an empty, same-uid, foreign-uid or SID subject
- **THEN** only empty and same-uid commands are host-owned and the proof does not remain after the call

#### Scenario: test_incomplete_or_remote_command_source_is_not_host
- **WHEN** command metadata is missing, lacks the relay flag, names a relay/messaging source or carries a detached route
- **THEN** policy-free local context does not grant host authority

#### Scenario: test_command_authority_resets_on_errors_and_overlapping_calls
- **WHEN** native and unproven commands overlap or a native handler raises
- **THEN** proof stays task-local and is reset on every exit

#### Scenario: test_core_signins_act_as_host_owner
- **WHEN** each bundled login reaches the native session directly or forwarded in a local ticket
- **THEN** actual core principal mapping yields the host subject and command identity is local on the prepared POSIX gateways

#### Scenario: test_relay_wire_host_surface_labels_are_not_host
- **WHEN** relay wire selects the CLI, TUI, Desktop or ACP label without a user
- **THEN** core's unknown-platform fallback remains remote and cannot grant host pairing authority
