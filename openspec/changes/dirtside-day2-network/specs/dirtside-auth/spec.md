# Spec Delta

## Purpose

Authenticate personal devices without granting them dashboard sessions and complete single-use pairing under either dashboard gate mode.

## ADDED Requirements

### Requirement: Pure device token recognition
The auth provider SHALL recognize active tokens and unexpired pending codes without changing credentials, online state or requests, and SHALL NOT issue interactive sessions. A retained principal SHALL authorize nothing inside Dirtside.

A revoked or replaced credential's ten-second window follows the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window reopens it, and setting it forward closes it early.

#### Scenario: test_window_edges_on_every_route
- **WHEN** a retained credential is checked with routes enabled through the public method
- **THEN** it is recognized from its first revoke or replacement through event+9, but not at event+10
- **AND** foreign bound routes refuse it, legacy unbound routes skip Dirtside while it has a bound policy, and it has no active authority inside Dirtside
- **AND** an offline or backed-off device missing the window retries generic rejection until manually stopped
- **AND** credentials replaced before this version were not retained and their old processes need manual shutdown

#### Scenario: Recognized credentials
- **WHEN** an active token or pending code is checked
- **THEN** a device-scoped principal is returned with no state changes

#### Scenario: Rejected credentials
- **WHEN** a token is unknown or its pending code is expired or revoked
- **THEN** recognition returns no principal and registered device paths return 401

#### Scenario: Retained paired credential
- **WHEN** a revoked paired token reaches any signed device route inside its ten-second window
- **THEN** a valid signature, 300-second freshness, unused nonce and matching sender/kind receive exact 401 detail=device revoked without touching live state
- **AND** every qualifying retry receives that answer; invalid proof never receives the explicit stop answer
- **AND** bad retained proof has a different generic body from an unknown bearer inside the window

#### Scenario: test_restart_keeps_window_and_resets_replay_guard
- **WHEN** the gateway restarts with a fresh registry, relay and replay guard inside the window
- **THEN** a captured message younger than 300 seconds can be replayed and receive the stop answer until event+10

#### Scenario: Re-pairing never starts a new window
- **WHEN** an already revoked name is paired again a day later
- **THEN** the old credential keeps its first revoke time and re-pairing never starts a new window

#### Scenario: Pairing code on another plugin's token route
- **WHEN** a pairing code reaches a foreign bound route or legacy unbound token route while Dirtside has a bound policy
- **THEN** core refuses it before and after use, revocation, replacement or expiry, while the foreign provider's own bearer passes
- **AND** a live unused code completes signed pairing on Dirtside's own route

### Requirement: Single-use signed pairing
Pairing SHALL prove possession of the hello key, bind the authenticated code to completion in one transaction, rotate to a long-lived token and return the relay public key.

#### Scenario: Pair with the gate engaged
- **WHEN** a device presents a minted code and correctly signed hello on the pair route
- **THEN** pairing succeeds and the code can no longer authenticate

#### Scenario: Pending code outside pairing
- **WHEN** a pending code calls poll, chunk or result
- **THEN** the route returns 401 without touching online state

#### Scenario: Code replaced during completion
- **WHEN** an already authenticated code is replaced by a new same-name code
- **THEN** completion with the old code fails without consuming the new code
