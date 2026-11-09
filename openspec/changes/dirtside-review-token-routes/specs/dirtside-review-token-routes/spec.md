## ADDED Requirements

### Requirement: Provider-bound routes
When available, the public seam MUST register all fixed paths for dirtside with exact scopes and retain disposable registrations.

#### Scenario: test_public_token_registration
- **WHEN** ctx exposes the proposed method
- **THEN** device paths require dirtside, local paths require dirtside-local and fallback is never called

#### Scenario: test_auth_registration_refusal_never_registers_routes
- **WHEN** core refuses the auth provider registration
- **THEN** the instance remains disabled and no token route is requested

#### Scenario: test_unload_closes_handlers
- **WHEN** the instance unloads with stale outer registrations and the dashboard gate on or off
- **THEN** all device and local handlers reject valid credentials before parsing

#### Scenario: test_disposal_failure_still_closes_routes
- **WHEN** one disposable raises during unload
- **THEN** every remaining disposable is attempted and the instance stays disabled

### Requirement: Atomic fail-closed registration
A raising or None-returning seam MUST disable every device and local route, roll back prior registrations and log one line.

#### Scenario: test_token_registration_refusal
- **WHEN** registration is refused after a partial success
- **THEN** all paths answer 401 or 404, never 200, with one clear log line

#### Scenario: test_registration_is_instance_owned
- **WHEN** one instance succeeds and another instance for the same home refuses
- **THEN** the refused instance stays disabled without disabling the successful one

#### Scenario: test_present_noncallable_seam_is_not_legacy
- **WHEN** the token-route attribute is present but not callable
- **THEN** registration fails closed without calling the legacy fallback

### Requirement: Released-core fallback
Without the method, registration MUST use the single lazy transitional function and keep full device flow working.

#### Scenario: test_legacy_token_registration
- **WHEN** either released checkout loads Dirtside
- **THEN** fallback registration and real pairing, polling and execution work

#### Scenario: test_legacy_registration_failure
- **WHEN** the released-core fallback fails after a partial registration
- **THEN** the instance stays disabled with one bounded log line

### Requirement: Independent credential checks
Handlers MUST reject device tokens on local routes and the local secret on device routes in both registration modes.

#### Scenario: test_cross_credentials
- **WHEN** credentials cross route classes with the dashboard gate on or off
- **THEN** the request is refused before device or local work
