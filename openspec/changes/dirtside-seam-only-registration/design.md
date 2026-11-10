# Design

## Context

See proposal.md for motivation. The method core is Hermes 0.23.1 (`3b421578588243f920886e6fe79a6faa87ea026e`) with the single public commit of core PR #151760 (`7dce8c38e8c998c52c4c139df340a0bffecc77e6`) applied. An unchanged full run has two assertions expecting the fallback's post-disable error body; doctor, validation and all eight loopback matrix cases pass. No baseline production defect was found.

## Goals / Non-goals

**Goals:** Remove the private route registration, retain instance-owned atomic closure and prove the actual public registration and gate.

**Non-goals:** Change actor identity, device ownership, protocol, dependencies, the ten-second revoke window, prompt caching, hooks or the two read-only environment imports.

## Decisions

- Use only the context method for all nine exact paths. Preserve the device and local scopes and reverse disposal. A missing or noncallable method, a None handle or an exception leaves the handler gate closed. Keeping private registration, writing policies directly or substituting a successful registrar would defeat the public boundary.
- Keep a short constant explanation on the route gate. Commands read its current explanation through the relay they already receive; successful status text and sender refusals stay intact. The standalone device CLI cannot inspect the gateway's context or diagnose a generic remote 401. Its pairing error gives a conditional method/version hint without another request or importing gateway modules.
- Use real PluginContext and PluginManager objects with an actually discovered dashboard directory. Inject failures around the real method only. Register the provider through that context, and dispose registrations and restore process-global state at fixture exit. Real rediscovery tests continue using the existing process rig.
- Follow core's `hermes_cli/plugins_context.py`, `PluginContext.register_dashboard_token_route`, lines 586 to 640 at public PR commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6`: registration is launch-owned, mount-confined and tied to this plugin's active provider handle. The handle removes only its own policy.
- Follow core's `hermes_cli/dashboard_auth/token_auth.py` at public PR commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6`: `_authenticate_bound_token`, lines 116 to 160, calls only the current owning provider and requires the matching TokenPrincipal provider, launch home and scopes; `token_auth_middleware`, lines 183 to 194, returns 503 when a provider raises `ProviderError`, 403 for insufficient scope or 401 for other rejection. Dirtside's provider never raises `ProviderError`. For a legacy unbound token route, `authenticate_token`, lines 86 to 113, skips providers with any current bound policy.
- Reject every credential before lookup while routes are closed, including after failure or unload when the provider remains registered. This also prevents admission to legacy token routes such as core's drain route.
- Make registration a no-op for an already enabled compatible runtime. Reload still unloads before registration; a separate profile load cannot replace launch authentication or its status guidance.
- Keep retained-token recognition exactly as implemented: routes enabled, from first revoke or replacement through the next ten whole gateway seconds. It is not active device authority. The bound gate removes the former foreign-route reason for that length; a longer window is possible but is not part of this change.
- Replace the two older CI jobs with one Ubuntu/macOS matrix. Fetch Hermes 0.23.1 and apply the public single-commit patch, excluding `website/*`, until a release contains the method.

## Risks / Trade-offs

- No released minimum version yet: leave the manifest value unchanged for preparation, clearly require the method, and update the version and CI pins when it ships.
- Disposal can remove every bound policy while a provider remains process-global; the provider's own closed-state check must then reject every credential.
- Remote authentication errors have several causes: keep device guidance conditional and preserve bounded, redacted server detail.
- This is not an owner live-device check. Keep dated measurements as history and tie new verification only to its tested source.

## Migration plan

No data migration or re-pairing. Install on a core containing the method. On an older core the plugin loads but device, local and dashboard control routes stay closed; chat revoke still works. The previous version remains the released-core line until a release contains the method. Catalog listing also waits for that release and the matching manifest floor and pin.
