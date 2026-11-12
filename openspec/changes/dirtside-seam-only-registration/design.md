# Design

## Context

The method core is Hermes 0.23.1 (`3b421578588243f920886e6fe79a6faa87ea026e`) with commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6` applied. That commit is the change of core PR #151760 as first submitted on 2026-11-09. The pull request was rebased onto newer Hermes on 2026-11-11 with the same code, and its source repository keeps this commit.

## Goals / Non-goals

**Goals:** Remove the private route registration, retain instance-owned atomic closure and prove the actual public registration and gate.

**Non-goals:** Change actor identity, device ownership, protocol, dependencies, the ten-second revoke window, prompt caching, hooks or the two read-only environment imports.

## Decisions

- Use only the context method for all nine exact paths. Preserve the device and local scopes and reverse disposal. A missing or noncallable method, a None handle or an exception leaves the handler gate closed. Keeping private registration, writing policies directly or substituting a successful registrar would defeat the public boundary.
- Commands and terminal prechecks read the current closure reason through the relay they already receive. Senders who may pair get that reason when choosing, listing or using a device; other senders retain their usual replies. Explicit server selection still works, without automatic server execution in place of a device. The standalone pairing error gives a conditional method/version hint without another request or importing gateway modules.
- Use real PluginContext and PluginManager objects with an actually discovered dashboard directory. Inject failures around the real method only. Register the provider through that context, and dispose registrations and restore process-global state at fixture exit. Real rediscovery tests continue using the existing process rig.
- Follow core's `hermes_cli/plugins_context.py`, `PluginContext.register_dashboard_token_route`, lines 586 to 640 at public commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6`: registration is launch-owned, mount-confined and tied to this plugin's active provider handle. The handle removes only its own policy.
- Follow core's `hermes_cli/dashboard_auth/token_auth.py` at public commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6`: `_authenticate_bound_token`, lines 116 to 160, calls only the current owning provider and requires the matching TokenPrincipal provider, launch home and scopes; `token_auth_middleware`, lines 183 to 194, returns 503 when a provider raises `ProviderError`, 403 for insufficient scope or 401 for other rejection. Dirtside's provider never raises `ProviderError`. For a legacy unbound token route, `authenticate_token`, lines 86 to 113, skips providers with any current bound policy.
- Recognition rejects every credential before lookup while routes are disabled or any of its nine route handles is inactive, including before a targeted unload removes the provider. Core's public `PluginRegistration.active` becomes false before release (core's `hermes_cli/plugins_ledger.py`, `PluginRegistration.active` and `PluginRegistration.dispose`, lines 54 to 65 at public commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6`). This also prevents admission to legacy token routes such as core's drain route.
- Make registration a no-op for an already enabled compatible runtime. Reload still unloads before registration; a separate profile load cannot replace launch authentication or its status guidance.
- A recorded owner in this process is not contacted over HTTP while the process's live registration is closed. Commands use local registry state, and revoke also cancels the retained relay's live work. A retired relay reads the live registration for the same database for this check and for closure replies, so a conversation cached before a disable reaches the owner again after re-enable. A profile-scoped load, whose database differs, keeps its own closed state.
- Local execution and stream attachment retry an owner's 401 within the existing three-second monotonic bound and preserve the request id. Core's gate, the instance gate and local-secret validation all refuse before execution or stream attachment. Other statuses, transport failures and successful streams are not replayed. Real-loader tests issue calls inside registrations 1, 5 and 9, with one marker append and one history row.
- Retained-token recognition keeps the ten-second window from first revoke or replacement, with routes enabled and active handles. It is not active device authority. A longer window is possible on the bound gate but is not part of this version.
- CI has one Ubuntu/macOS matrix. Git fetches Hermes 0.23.1 from the upstream repository and the exact public method commit with its parent, by object id, from the pull request's source repository. The parent-to-commit difference applies with `website/*` excluded until a release contains the method.

## Risks / Trade-offs

- No released minimum version exists yet. The plugin version remains `0.1.0` and `requires_hermes` remains `>=0.22.7`; the version label and manifest floor move together when a Hermes release contains the method.
- Disposal can remove every bound policy while a provider remains process-global; the provider's own closed-state check must then reject every credential.
- Remote authentication errors have several causes: keep device guidance conditional and preserve bounded, redacted server detail.

## Migration plan

No data migration or re-pairing. Install on a core containing the method. On an older core the plugin loads but device, local and dashboard control routes stay closed; chat revoke still works. The previous version remains the released-core line until a release contains the method. Catalog listing also waits for that release and the matching manifest floor and pin.
