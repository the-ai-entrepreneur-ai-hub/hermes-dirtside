# Spec Delta

## Purpose

Keep conversation device selections valid when a user pairs replacement credentials under the same device name.

## ADDED Requirements

### Requirement: Stable replacement identity
Re-pairing an existing named device SHALL retain its device id while rotating its bearer and signing public key atomically. The consumed code and former bearer SHALL no longer authorize device work.

#### Scenario: Chosen device is paired again
- **WHEN** a conversation chooses a device and that name is paired with a new key
- **THEN** the conversation executes on the replacement without another target choice
- **AND** the former bearer is rejected

#### Scenario: Explicit replacement restores a revoked name
- **WHEN** a user revokes a chosen device and completes a fresh authenticated pairing for that name
- **THEN** the existing conversation choice resolves to the replacement without choosing again
- **AND** neither the consumed code nor the former bearer authorizes device work

#### Scenario: An old authenticated poll is still parked
- **WHEN** replacement pairing rotates the signing key while an older poll waits
- **THEN** that older poll receives the plugin's revocation response instead of newly queued work
- **AND** only the replacement's signed poll restores online presence and receives the work

#### Scenario: Replacement requests overlap
- **WHEN** two authenticated replacement pairings overlap
- **THEN** relay key publication follows credential commit order
- **AND** the currently paired key can poll successfully
