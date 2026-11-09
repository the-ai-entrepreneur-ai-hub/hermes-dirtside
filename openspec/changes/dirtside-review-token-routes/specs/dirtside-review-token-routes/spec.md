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

### Requirement: Live registration rebinding
An already-mounted router MUST use the currently registered provider and its registry for each request, and MUST preserve live device work through successful rediscovery.

#### Scenario: test_force_rediscovery_keeps_device_and_local_calls_working
- **WHEN** real discover_and_load(force=True) runs during device work in either transport
- **THEN** the in-flight command, next signed poll, local IPC and next cached-environment command all succeed

#### Scenario: test_disabled_then_reenabled_plugin_reuses_mounted_router
- **WHEN** the real core configuration disables the plugin and later enables it with forced discovery
- **THEN** all mounted device/local paths stay closed while disabled and the same mounted router works after re-enable

#### Scenario: test_mounted_router_uses_replacement_registry_and_refuses_failed_instance
- **WHEN** a mounted router gets a replacement registry and then a refused instance
- **THEN** only current credentials work before refusal and all routes close after refusal with either outer gate mode

### Requirement: Versioned runtime continuity
Registration MUST reuse only a compatible explicitly marked runtime. Cached retired environments MUST reach the current serving owner or fail quickly, never queue into a relay no device polls.

#### Scenario: test_upgrade_from_unmarked_provider_starts_fresh_runtime
- **WHEN** the previous provider has the catalog-pin shape without C1 runtime fields
- **THEN** registration succeeds with a fresh compatible runtime

#### Scenario: test_unloaded_owner_relay_uses_client_not_retired_queue
- **WHEN** an owner runtime's token-route registrations are disposed
- **THEN** its connection is the Client rather than its abandoned local relay

#### Scenario: test_cached_conversation_survives_disable_enable
- **WHEN** real core disable and enable occur after an environment was cached in either transport
- **THEN** the same cached environment's next command executes successfully on the device without a restart

#### Scenario: test_unclaimed_local_owner_fails_fast
- **WHEN** a re-enabled relay has not yet received its first device poll but its old owner address points back to this server
- **THEN** local state and revoke calls fail quickly instead of recursively forwarding, while independent secondary forwarding remains supported

### Requirement: Module-generation state compatibility
Mounted handlers MUST interpret terminal states by their serialized values across module generations.

#### Scenario: test_mounted_generations_close_and_kill_after_reload
- **WHEN** disable/enable and forced rediscovery retain first-generation mounted methods
- **THEN** close accepts their terminal outcome and local kill reports true for a cancelled current handle

### Requirement: Explicit agent revocation signal
The agent MUST stop permanently only for exact HTTP 401 detail=device revoked. Generic core authentication failures, unknown credentials and transient failures MUST retry using existing backoff.

#### Scenario: test_agent_retries_generic_core_rejection
- **WHEN** core rejects a request before the plugin route with the generic unauthenticated body
- **THEN** polling retries while the agent stays alive until its owner stops it

#### Scenario: test_foreign_poll_401_keeps_execution_alive_and_polls_again
- **WHEN** polling returns a generic, unknown-credential or foreign 401
- **THEN** the agent retries and retains its live work

#### Scenario: test_foreign_upload_401_retries_without_shutdown
- **WHEN** chunk or result upload returns an ambiguous authentication rejection
- **THEN** upload retries and can succeed without shutting down the agent

#### Scenario: test_plugin_revocation_exits_subprocess_successfully
- **WHEN** a subprocess receives exact explicit revocation, with or without an earlier unknown-credential response
- **THEN** only the explicit signal ends serving successfully within the original bound

#### Scenario: test_core_credential_rejection_requires_exact_body
- **WHEN** 401 or a non-401 response carries revoked, generic, unknown-credential or foreign JSON
- **THEN** only exact 401 detail=device revoked is a shutdown signal

#### Scenario: test_cli_pair_real_http_pwd_cd_stop_revoke
- **WHEN** a subprocess has executed and interrupted real device work and transport loses the revocation detail
- **THEN** gateway requests cancel immediately, the agent retries twice, and owner stop shuts it down within the original bound

#### Scenario: test_full_pair_execute_cancel_revoke_path_with_thread_agent
- **WHEN** the thread agent completes real execution and interruption but receives only generic 401 after revocation
- **THEN** it stays alive through retries until its owner stops it without leaking the thread

### Requirement: Bounded exact reload-window retry
The client MUST limit retries to /exec and /stream HTTP 401 with raw JSON detail exactly Dirtside token routes are disabled, within one fixed three-second deadline per operation with unchanged request id and captured owner. No ambiguous execution or successful stream MAY be replayed.

#### Scenario: test_exact_disabled_route_retries_preserve_request
- **WHEN** either execution submission or stream attachment sees three exact disabled-route refusals before success
- **THEN** the same request id is used and every rejected response is closed

#### Scenario: test_other_rejections_are_never_retried
- **WHEN** detail spelling or status differs, or the rejection body is malformed
- **THEN** execution fails or the handle becomes lost after one attempt without replay

#### Scenario: test_disabled_route_retry_has_one_fixed_short_deadline
- **WHEN** the exact disabled-route refusal persists
- **THEN** retries stop after the fixed short window with the original refusal and closed responses

#### Scenario: test_disabled_response_does_not_retry_other_local_routes
- **WHEN** device-state or cancellation routes receive that exact refusal
- **THEN** each call fails without retry

#### Scenario: test_real_local_route_recovers_without_duplicate_execution
- **WHEN** a real signed device command encounters the exact refusal before /exec or /stream
- **THEN** recovery produces one device marker append, one history row and the complete outcome
