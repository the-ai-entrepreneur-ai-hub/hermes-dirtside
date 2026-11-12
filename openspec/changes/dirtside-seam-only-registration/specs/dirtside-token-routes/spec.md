## Purpose

Keep device and local credentials behind public, provider-bound token routes, with complete closure and useful guidance when registration cannot succeed.

## ADDED Requirements

### Requirement: Atomic public registration
The plugin SHALL open its four device and five local paths only after all public registrations succeed, bound to Dirtside with their existing device or local scopes. It SHALL close all handlers and dispose acquired registrations on refusal, failure or unload.

#### Scenario: Real registration succeeds
- **WHEN** Hermes accepts every route through the public context method
- **THEN** the device and local paths work with their own credentials and unload closes every handler

#### Scenario: A registration is refused or fails
- **WHEN** the first, fifth or ninth registration returns no handle or raises
- **THEN** all acquired handles are disposed, every device and local handler stays closed, and no private route registration occurs

#### Scenario: Disposal raises
- **WHEN** one acquired handle raises during disposal
- **THEN** the handler gate closes first and disposal still attempts every other acquired handle

#### Scenario: Registration repeats without unload
- **WHEN** core loads the same compatible runtime again while its routes are enabled
- **THEN** registration leaves its provider, routes, commands and status intact, and a later unload and reload still succeeds

#### Scenario: A profile loads beside the launch scope
- **WHEN** a separate profile manager loads the plugin and core ignores its provider and token-route registrations
- **THEN** the working launch provider, routes and status remain unchanged

### Requirement: Closed credentials are inert
While its routes are disabled or any public route handle is inactive, the provider SHALL recognize no credential before any lookup. Device, local and dashboard control routes SHALL stay closed, while authorized chat revoke remains available.

#### Scenario: Another token route after closure
- **WHEN** the method is missing, registration is refused part-way or the plugin is unloaded
- **THEN** active bearers, pending codes, local secrets and retained bearers all receive 401 on a legacy token route, while that route's own token still succeeds

#### Scenario: Targeted unload before provider removal
- **WHEN** core disposes route handles before unregistering the provider or calling the unload callback
- **THEN** all four credential kinds receive 401 on the drain route even while the instance flag is still enabled, and the drain route's own token succeeds

#### Scenario: Dashboard session after closure
- **WHEN** the method is missing, registration is refused part-way or the plugin is unloaded
- **THEN** the dashboard session token receives 401 with `Dirtside token routes are disabled` on device listing and pairing while unrelated session routes still work

### Requirement: Closure without the method
The plugin SHALL load without opening device or local routes when the public method is missing or noncallable. Its bounded warning SHALL identify that cause without exception contents.

#### Scenario: Older Hermes
- **WHEN** the plugin loads on Hermes without the public method
- **THEN** every device and local route stays closed, the warning explains that Hermes is too old, and the private registrar is never called

### Requirement: Provider and scope isolation
On the supported core the plugin's credentials SHALL NOT authorize another provider's bound routes or legacy unbound token routes while Dirtside has a bound policy. Its device and local scopes SHALL NOT substitute for each other.

#### Scenario: Foreign token route
- **WHEN** an active bearer, live pairing code, local secret or in-window retained bearer is sent to a foreign token route while Dirtside has bound paths
- **THEN** core returns 401 while the foreign provider's own bearer succeeds and the Dirtside credential reaches its own appropriate path

#### Scenario: Wrong Dirtside scope
- **WHEN** a recognized device credential is used on a local route or the local secret is used on a device route
- **THEN** core returns 403 for insufficient scope and the correctly scoped credentials still work

### Requirement: Current closure guidance
Senders who may pair SHALL receive the current closure reason from pairing, status, device selection, device lists and terminal prechecks, without advice to start the device. Other senders SHALL retain their usual replies. Explicit server selection SHALL remain available, without automatic server execution in place of a device. Device pairing authentication errors SHALL identify the required gateway method conditionally, without claiming every 401 proves an old Hermes or making another request.

#### Scenario: Commands with closed routes
- **WHEN** a sender who may pair chooses, lists or uses a device after registration cannot succeed
- **THEN** the reply names the current closure cause, gives no device-start advice and never executes on the server instead

#### Scenario: Refused reload after device contact
- **WHEN** an owner record names this process and the fifth registration is refused during a real reload
- **THEN** commands act locally, revoke succeeds and cancels live work, and device-dependent replies explain closure

#### Scenario: Cached conversation after re-enable
- **WHEN** a conversation cached before a disable runs a command after the plugin is enabled again in the same process
- **THEN** it reaches the current owner through loopback and is not answered with the retired registration's closure reason

#### Scenario: Profile-scoped load beside an open launch registration
- **WHEN** the plugin is also loaded for a profile whose database differs from the launch registration's
- **THEN** that load's pairing and status give its own closure reason, and pairing mints no code

#### Scenario: Remote pairing authentication failure
- **WHEN** the device receives an authentication failure while pairing
- **THEN** its bounded, redacted error includes a conditional reminder that older Hermes without the public method keeps these routes closed

### Requirement: Unchanged revoke window
Retained credentials SHALL remain recognized only while routes are enabled and the whole-second gateway clock is within ten seconds of first revoke or replacement. Signed proof remains required for the explicit stop answer; active device authority remains separate.

#### Scenario: Window boundaries
- **WHEN** valid retired-device proof arrives before the window, inside it, at its endpoint or after a clock change
- **THEN** the existing recognition and proof-first stop rules hold without extending the window or authorizing foreign bound routes

### Requirement: Bounded worker replay
Local execution and stream attachment SHALL retry an owner's pre-handler 401 within one fixed three-second deadline per operation, using the same request id and captured owner. Other statuses, transport failures and successful streams SHALL NOT be replayed.

#### Scenario: A call inside real reload
- **WHEN** a worker call reaches the owner during registration 1, 5 or 9
- **THEN** it receives core's actual 401 before handler work, retries after reload and produces one marker append, one history row and the complete outcome

#### Scenario: A permanently closed recorded owner
- **WHEN** a worker execution request repeatedly receives the owner's 401
- **THEN** the same deadline ends replay without submitting work; core may independently retry a terminal failure
