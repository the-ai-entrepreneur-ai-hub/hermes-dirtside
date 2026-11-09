## ADDED Requirements

### Requirement: Provider-bound routes
When available, the public seam MUST register all fixed paths for dirtside with exact scopes and retain disposable registrations.

#### Scenario: test_public_token_registration
- **WHEN** ctx exposes the proposed method
- **THEN** device paths require dirtside, local paths require dirtside-local and fallback is never called

### Requirement: Atomic fail-closed registration
A raising or None-returning seam MUST disable every device route, roll back prior registrations and log one line.

#### Scenario: test_token_registration_refusal
- **WHEN** registration is refused after a partial success
- **THEN** all paths answer 401 or 404, never 200, with one clear log line

### Requirement: Released-core fallback
Without the method, registration MUST use the single lazy transitional function and keep full device flow working.

#### Scenario: test_legacy_token_registration
- **WHEN** either released checkout loads Dirtside
- **THEN** fallback registration and real pairing, polling and execution work

### Requirement: Independent credential checks
Handlers MUST reject device tokens on local routes and the local secret on device routes in both registration modes.

#### Scenario: test_cross_credentials
- **WHEN** credentials cross route classes with the dashboard gate on or off
- **THEN** the request is refused before device or local work
