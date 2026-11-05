# Spec Delta

## Purpose

Authenticate personal devices without granting them dashboard sessions and complete single-use pairing under either dashboard gate mode.

## ADDED Requirements

### Requirement: Pure device token recognition
The auth provider SHALL recognize active device tokens and unexpired pending codes without changing credentials, online state or requests, and SHALL NOT issue interactive sessions.

#### Scenario: Recognized credentials
- **WHEN** an active token or pending code is checked
- **THEN** a device-scoped principal is returned with no state changes

#### Scenario: Rejected credentials
- **WHEN** a token is unknown, expired or revoked
- **THEN** recognition returns no principal and registered device paths return 401

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
