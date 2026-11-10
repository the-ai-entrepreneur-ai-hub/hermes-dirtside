# Spec Delta

## Purpose

Keep device authority with the current input's actor rather than a conversation's delivery route, while preserving established host authority and valid older-core sender behavior.

## ADDED Requirements

### Requirement: Current actor owns sender authority

Dirtside SHALL use the current actor for device authority only where core exposes actor binding. Otherwise it SHALL use the route user without reading an environment actor. On a capable core only a `None` actor SHALL fall back to the route. An empty actor beside a named route SHALL return missing identity before any host or cron rule.

#### Scenario: Shared route has an owner actor
- **WHEN** a shared chat route has no user and its actor owns the selected device
- **THEN** terminal and file dispatch are admitted and current target facts and newly frozen target sections identify that device

#### Scenario: Shared route has another or missing actor
- **GIVEN** the owner actor can execute on the selected device
- **WHEN** another actor or an empty actor attempts the same explicitly selected device
- **THEN** the request is refused without running on either device or server and without newly disclosing its target facts

### Requirement: Merged input removes single-sender authority

When core clears the actor after different senders' inputs join one running turn, a retained route user SHALL NOT restore device authority. On every platform, an empty identity whose route still names a user SHALL refuse further calls without server execution, whether the device was chosen explicitly or applied as the captured default. With an empty route, the sender-less requirement below SHALL apply. Earlier prompt and history facts SHALL remain unchanged.

#### Scenario: Another sender joins a turn with an explicit device
- **GIVEN** the owner has executed on an explicitly selected device through a turn's cached environment
- **WHEN** core absorbs another sender's input and clears the actor while retaining the route user
- **THEN** further device dispatch is refused, including in a previously copied context, without server fallback

#### Scenario: Another sender joins a turn with a default device
- **GIVEN** the owner has executed under the conversation's captured device default
- **WHEN** another sender's input clears the actor in the same cached environment while the route still names the first user
- **THEN** further calls are refused, no more requests reach the device, nothing runs on the server, and no mid-turn target update is assumed

#### Scenario: A listed platform loses its sender beside a named route
- **GIVEN** a canonical CLI `local`, `webhook`, `api_server` or wire-relay-labelled `local` turn can use its owner's chosen or default device
- **WHEN** another sender's input clears its actor while its route still names the first user
- **THEN** further calls refuse without server execution on each platform, while the owner and same-sender inputs before the merge retain device authority

#### Scenario: A constructed listed-surface merge has no route user
- **GIVEN** an empty-route shared binding on `webhook`, `api_server`, `msgraph_webhook` or `local` can use its owner's device
- **WHEN** another sender's input clears the actor while the route remains empty
- **THEN** the default device falls back to server, an explicitly chosen device refuses, and earlier prompt facts remain unchanged; the same constructed Telegram binding refuses both choices

#### Scenario: The same sender adds input
- **WHEN** core absorbs input from the same owner in the same route
- **THEN** that actor retains device authority and current target facts

### Requirement: Sender-less device resolution checks the route before the platform

When a device applies, empty identity with a named route SHALL refuse on every platform without server execution. With identity and route both empty, the turn SHALL refuse except on the plugin's eleven listed surfaces, which retain default-to-server fallback. The guard SHALL read the route once and normalize the platform, not classify by source. Explicit server and cron SHALL retain their rules.

#### Scenario: A sender-less device call has a named route
- **WHEN** `Access.identity()` is empty and `HERMES_SESSION_USER_ID` is nonempty under a chosen or default device on any platform
- **THEN** the call refuses, says the turn has no single sender and nothing ran on the server, and asks for a new message or `/dirtside use server`

#### Scenario: A messaging event arrives without a user
- **GIVEN** a device default applies to the conversation
- **WHEN** a messaging event has no sender on any supported core
- **THEN** the call refuses with the recovery text, no command runs on the server, and no request reaches the device

#### Scenario: A listed surface has no route user
- **GIVEN** the listed surfaces are empty platform, `api_server`, `cli`, `desktop`, `gateway`, `kanban`, `local`, `msgraph_webhook`, `tool`, `tui` and `webhook`
- **WHEN** both sender identity and route are empty on any of the eleven listed surfaces
- **THEN** a device default retains server fallback after stripping spaces and lowering the platform's case, while a normalized messaging platform still refuses

#### Scenario: A named route cannot produce a valid sender on an older core
- **WHEN** identity is empty beside a named route, even without actor binding
- **THEN** a chosen or default device refuses without server execution, while a valid named sender remains able to use its device

#### Scenario: A webhook user id is unprintable
- **GIVEN** a valid webhook owner can use the chosen or default device
- **WHEN** a webhook route names an unprintable user and identity is empty, on any checked core
- **THEN** both choices refuse with no server execution

#### Scenario: An explicit server choice overrides a device default
- **WHEN** a sender-less messaging turn explicitly chooses server
- **THEN** commands run on the server as before

### Requirement: Commands share actor authority

Device selection, listing, pairing, revocation and the picker SHALL use the same current-actor authority as execution. Choosing the server SHALL retain its existing behavior.

#### Scenario: Each participant controls only usable devices
- **WHEN** two actors use commands on the same shared route
- **THEN** each can select, list, pair and revoke within existing ownership rules, cannot claim the other's device, and sees only usable devices plus server in the picker

#### Scenario: Status has no sender under a paired default
- **GIVEN** the owner's device list reports the default device online
- **WHEN** a turn asks for bare status and device resolution raises the no-sender refusal
- **THEN** status says no device applies to a turn without a sender, retains the refusal and recovery text, and does not call that paired device unpaired

#### Scenario: Another refusal occurs beside an invalid sender
- **GIVEN** a valid webhook owner could use its default device before it was retired
- **WHEN** a turn without a valid sender asks for status and resolution finds that default unpaired
- **THEN** status keeps the unpaired-device answer rather than wrapping it as a no-sender refusal; classification uses the exception type without rereading identity or matching its text

### Requirement: Scoped follow-ups have current sender authority

A queued follow-up SHALL use its own actor rather than the opener's actor. Mixed-sender input SHALL remove that follow-up's device authority. Leaving the follow-up scope SHALL restore the opener's authority.

#### Scenario: The opener steers into a follower's queued input
- **GIVEN** a follow-up can use its sender's device but not the opener's device
- **WHEN** the opener's input is folded into that follow-up
- **THEN** its sender is missing, neither device is authorized, and scope exit restores the opener's original sender

### Requirement: Implicit server resolution is disclosed

An interactive conversation with no choice whose captured device default resolves to server SHALL receive the fixed server line at turn start, even after a reload. This applies to known unauthorized senders and listed surfaces with identity and route both empty, not an empty identity beside a named route or an unlisted sender-less platform under a device default. A server-default conversation with no choice SHALL remain silent.

#### Scenario: A non-owner enters after the owner's prompt was frozen
- **GIVEN** the conversation captured a device default and froze device facts for its owner
- **WHEN** a non-owner's turn resolves to server, including after a configuration reload to server
- **THEN** the start-of-turn hook says commands run on the server, adds no device facts, and leaves the frozen section unchanged

#### Scenario: An API or ambiguous direct ACP turn has no sender
- **GIVEN** the owner can use a device through the captured default
- **WHEN** an API-server or direct-ACP-equivalent turn with both sender identity and route empty uses that conversation, even with a messaging source label
- **THEN** commands retain server execution, do not reach the device, and the target line at the start of the turn says server

### Requirement: Existing host and compatibility rules remain

Dirtside SHALL preserve local provenance, native command-source checks, configured owners and direct-Python host authority. Host and cron rules for an empty actor SHALL apply only when the route also names no user. It SHALL NOT infer host authority from a relayed local label.

#### Scenario: Supported host and absent actor
- **WHEN** an established CLI, TUI, Desktop, ACP or cron host context has no actor value
- **THEN** its existing route-user and no-user authority rules apply without granting authority to a relayed label

#### Scenario: Empty actor and route retain no-user host authority
- **WHEN** both actor and route are empty in an established host or cron context
- **THEN** its existing no-user authority applies, while an empty actor beside any named route returns missing identity

#### Scenario: Older bound route ignores an environment actor
- **WHEN** core exposes no actor binding and a bound non-owner route has an owner actor planted in the process environment
- **THEN** the sender remains the bound route user, its own device remains usable, and the planted owner grants no device or local-host authority

#### Scenario: Worker transports current authority
- **WHEN** a worker sends a device request to the serving relay through authenticated local IPC
- **THEN** the carried current sender is checked against device ownership rather than inferred from the listener's unbound session context
