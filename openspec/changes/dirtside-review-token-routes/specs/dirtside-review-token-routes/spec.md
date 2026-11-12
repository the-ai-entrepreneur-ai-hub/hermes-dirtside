## ADDED Requirements

### Requirement: Provider-bound routes
The public method MUST register all fixed paths for dirtside with exact scopes and retain disposable registrations. The seam-only change supersedes this record's earlier fallback assumptions.

#### Scenario: test_public_token_registration
- **WHEN** the real core context exposes the public method
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

#### Scenario: Noncallable public method
- **WHEN** the token-route attribute is present but not callable
- **THEN** registration fails closed without private route registration

### Requirement: Missing-method closure
Without a callable public method, the plugin MUST load with every device and local handler closed, a bounded cause warning and no private route registration.

#### Scenario: Older Hermes
- **WHEN** Hermes lacks the public method
- **THEN** every device and local handler stays closed and pairing and status explain the missing method

#### Scenario: Real-method positive control
- **WHEN** the same plugin registers on the method core
- **THEN** its own device and local credentials reach their correctly scoped paths

### Requirement: Independent credential checks
The bound gate MUST reject device tokens on local routes and the local secret on device routes with 403 insufficient scope; handlers MUST retain their independent credential checks.

#### Scenario: test_cross_credentials
- **WHEN** credentials cross route classes with the dashboard gate on or off
- **THEN** the request is refused before device or local work

### Requirement: Live registration rebinding
An already-mounted router MUST use the currently registered provider and its registry for each request, and MUST preserve live device work through compatible successful rediscovery.

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
Registration MUST reuse only a same-path runtime explicitly marked version 2. Version 1 MUST build a fresh Registry and Relay. Cached retired environments MUST reach the current serving owner or fail quickly, never queue into a relay no device polls.

#### Scenario: test_upgrade_from_unmarked_provider_starts_fresh_runtime
- **WHEN** the previous provider has the previous catalog version's shape without versioned runtime fields
- **THEN** registration succeeds with a fresh compatible runtime

#### Scenario: test_reload_refreshes_v1_lookup_and_keeps_v2_runtime
- **WHEN** the previous provider has runtime_version 1 with the old credential lookup API, or version 2 on the same path
- **THEN** version 1 receives a fresh registry and relay, version 2 keeps both, and a paired device authenticates through the real core gate

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
- **WHEN** an unknown bearer makes core itself return its unchanged generic unauthenticated body
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

### Requirement: Bounded reload-window retry
The client MUST limit retries to an owner's /exec and /stream HTTP 401, which precedes handler work, within one fixed three-second deadline per operation with unchanged request id and captured owner. No other status, transport failure, ambiguous execution or successful stream MAY be replayed.

#### Scenario: test_worker_call_inside_real_reload_is_replayed_once
- **WHEN** a worker reaches the real owner during registration 1, 5 or 9, including before execution submission or stream attachment
- **THEN** core's actual 401 precedes recovery, the same request id is retained, and one marker append, one history row and the complete outcome prove one execution

#### Scenario: test_worker_terminal_inside_real_reload_recovers_through_core_retry
- **WHEN** a worker terminal call reads device state from the real owner during registration 1, 5 or 9
- **THEN** the client does not replay the refused read, and core's own terminal retry completes the call at least two seconds later with one marker append and one history row

#### Scenario: test_other_real_owner_refusals_are_not_replayed
- **WHEN** the real owner returns 400, 403, 409, 410 or 503
- **THEN** the client reports that refusal after one attempt without adding work, and a live local state control still succeeds

#### Scenario: test_worker_with_stale_closed_owner_stops_at_the_same_deadline
- **WHEN** a recorded owner has permanently closed routes
- **THEN** execution replay ends at the same three-second client deadline without work

#### Scenario: test_worker_terminal_with_stale_closed_owner_ends_with_core_retries
- **WHEN** a worker terminal call finds a recorded owner with permanently closed routes
- **THEN** each of core's four terminal attempts makes one refused device-state read, and the call ends without work

#### Scenario: test_dropped_connection_is_a_single_attempt
- **WHEN** the recorded owner drops the connection during execution submission or stream attachment
- **THEN** the client makes one attempt and reports the missing owner

### Requirement: Proof-first revocation on every signed route
A retained paired credential MUST receive exact HTTP 401 detail=device revoked inside its ten-second window only after valid signature, 300-second freshness, nonce, sender and route-kind checks. No open poll is required. Default registry authority MUST remain active-only. Rejected traffic MUST NOT publish ownership or update liveness or work.

#### Scenario: test_revoked_key_gets_explicit_rejection_on_every_route
- **WHEN** the revoked key validly signs pairing, polling, chunk or result traffic inside the window with either dashboard gate mode
- **THEN** each qualifying contact receives the exact stop response without relay work or owner publication

#### Scenario: test_invalid_requests_never_get_explicit_stop_answer
- **WHEN** the signature, identity, timestamp, kind, bearer or message is invalid or unsigned
- **THEN** rejection remains generic and never receives the explicit stop answer
- **AND** bad retained proof and an unknown bearer have different generic bodies inside the window

#### Scenario: test_pre_revoke_signed_request_cannot_be_replayed
- **WHEN** a previously accepted signed request is replayed after revocation
- **THEN** it receives generic rejection, while a freshly signed request receives the exact stop response

#### Scenario: test_revoked_key_survives_gateway_restart
- **WHEN** the gateway restarts after revocation without the old live relay
- **THEN** valid proof receives the stop inside the persisted ten-second window

#### Scenario: test_revoke_between_lookup_and_verification_does_not_dispatch
- **WHEN** revocation persists after credential capture but before signed verification completes
- **THEN** valid proof receives the exact stop even in the revoke second, without liveness, owner publication or dispatch

#### Scenario: test_offline_revoked_agent_stops_without_parked_poll
- **WHEN** an agent was offline at revocation and reconnects inside the ten-second window
- **THEN** qualifying signed contact learns revocation and the real subprocess exits successfully within five seconds

#### Scenario: test_real_agent_upload_stops_without_an_open_poll
- **WHEN** real execution uploads a qualifying chunk or result inside the ten-second window while no poll is open
- **THEN** the upload receives the exact stop response, the agent shuts down and its running process group stops

### Requirement: Retired credential isolation across re-pairing
Same-owner re-pairing MUST preserve the existing device id and conversation selection while retaining the old paired key and token hash separately. Old proof MUST NOT gain active authority or affect the replacement.

#### Scenario: test_repair_keeps_retired_key_separate_from_new_device
- **WHEN** the same owner re-pairs an active or revoked identity
- **THEN** every old qualifying proof inside the first ten seconds receives the stop, the new key executes normally and the old key cannot use the new bearer

#### Scenario: test_retired_bearer_never_grants_local_or_dashboard_authority
- **WHEN** a revoked or replaced bearer crosses into local IPC, pairing management, device revocation or a gated dashboard route
- **THEN** the same request without a bearer is refused, the retained bearer is also refused and no work or management side effect occurs

#### Scenario: test_retired_lookup_is_not_active_authority
- **WHEN** transport opts into a retained paired key
- **THEN** it receives a separate revoked record, while default lookup, active device queries and revoked or expired pending codes remain closed

### Requirement: One revoke window per credential
Retained recognition SHALL require enabled routes and `revoked_at <= now < revoked_at + REVOKE_NOTICE_S`, with `REVOKE_NOTICE_S = 10`, through the public method. Requests with valid signed proof inside the window SHALL receive the stop. Failed, refused or unloaded routes SHALL remain closed. Archival SHALL preserve the time of the first revoke or replacement; re-pairing an already revoked name never starts a new window.

#### Scenario: test_window_edges_on_every_route
- **WHEN** revoke or replacement happens through the public method
- **THEN** all four signed routes give the stop at event+0 and event+9 and core gives its own generic rejection at event+10
- **AND** foreign bound routes and legacy unbound routes refuse Dirtside credentials while Dirtside has a bound policy; the foreign provider's own bearer passes and the Dirtside credential reaches its appropriate own route

#### Scenario: test_independent_device_clock_gets_notice
- **WHEN** the device signs in the revoke second or its timestamp is 60 seconds behind or ahead
- **THEN** valid 300-second-fresh proof receives the stop inside the window without an artificial retry

#### Scenario: test_retries_each_get_notice_inside_window
- **WHEN** several fresh signed requests use one retained bearer inside the window
- **THEN** each receives the explicit stop answer

#### Scenario: test_parked_poll_does_not_consume_later_answers
- **WHEN** a parked poll has received an answer that the device might not have received
- **THEN** subsequent qualifying requests still each receive the stop inside the window

#### Scenario: test_restart_keeps_window_and_resets_replay_guard
- **WHEN** fresh registry, relay and replay guard restart inside the window
- **THEN** valid proof receives the stop through event+9 and core rejects at event+10
- **AND** the empty replay cache permits a captured message younger than 300 seconds to receive the stop

#### Scenario: Re-pairing never starts a new window
- **WHEN** an already revoked name is paired again a day later by the same or a different owner
- **THEN** the old credential keeps the time of its first revoke or replacement and re-pairing never starts a new window

#### Scenario: test_registration_failure_still_closes_retained_bearer
- **WHEN** the public registration API refuses a route
- **THEN** the instance recognizes no retained bearer even inside the window while the foreign provider's positive control still succeeds

#### Scenario: test_invalid_proof_never_gets_stop_inside_or_after_window
- **WHEN** proof has a bad signature, sender, kind, stale timestamp, reused nonce or no signature
- **THEN** it never receives the explicit stop answer inside or outside the window

#### Scenario: test_real_poll_loop_stops_between_polls_only_inside_window
- **WHEN** a real device is revoked between polls and its next poll reaches core
- **THEN** it exits on the next poll inside the window, but keeps retrying core's own generic body after it until stopped by hand
- **AND** pre-version replacement credentials remain unavailable and require manual shutdown

### Requirement: Gateway clock controls the window
The window SHALL follow the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window SHALL reopen recognition, and setting it forward SHALL close it early.

#### Scenario: Clock set back into the window
- **WHEN** a retained bearer is checked at revoke+5, revoke+10, then the clock is set back to revoke+5 and revoke-1
- **THEN** Dirtside's signed route gives the stop, core rejection, stop and core rejection respectively, with foreign routes refusing throughout while a Dirtside policy remains bound
- **AND** that plugin's own bearer passes at each step
