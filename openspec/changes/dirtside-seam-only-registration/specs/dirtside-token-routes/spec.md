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
While its routes are closed for any reason, the provider SHALL recognize no credential before any lookup. Device, local and dashboard control routes SHALL stay closed, while authorized chat revoke remains available.

#### Scenario: Another token route after closure
- **WHEN** the method is missing, registration is refused part-way or the plugin is unloaded
- **THEN** active bearers, pending codes, local secrets and retained bearers all receive 401 on a legacy token route, while that route's own token still succeeds

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
Pairing and status replies SHALL explain the current route closure cause without changing sender authorization. Device pairing authentication errors SHALL identify the required gateway method conditionally, without claiming every 401 proves an old Hermes or making another request.

#### Scenario: Commands with closed routes
- **WHEN** an authorized sender asks to pair or inspect status after registration cannot succeed
- **THEN** the reply names the current closure cause and pairing does not mint an unusable code

#### Scenario: Remote pairing authentication failure
- **WHEN** the device receives an authentication failure while pairing
- **THEN** its bounded, redacted error includes a conditional reminder that older Hermes without the public method keeps these routes closed

### Requirement: Unchanged revoke window
Retained credentials SHALL remain recognized only while routes are enabled and the whole-second gateway clock is within ten seconds of first revoke or replacement. Signed proof remains required for the explicit stop answer; active device authority remains separate.

#### Scenario: Window boundaries
- **WHEN** valid retired-device proof arrives before the window, inside it, at its endpoint or after a clock change
- **THEN** the existing recognition and proof-first stop rules hold without extending the window or authorizing foreign bound routes
