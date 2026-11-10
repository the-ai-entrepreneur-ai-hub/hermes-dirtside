# Provider-bound device token routes

## Why

Catalog admission needs token routes registered through the public context method, not core's private route set. Prepare this version for the first Hermes release containing that method, without changing the device protocol or actor rules.

## What changes

- **BREAKING:** Require `ctx.register_dashboard_token_route` for all four device and five local paths. Older Hermes loads the plugin with those routes closed.
- Keep atomic rollback and unload disposal. Explain a missing method, a refusal or a failure in the warning and route-dependent replies, without exposing exception contents.
- Recognize no credentials while routes are closed, including on other token routes, and keep an already enabled runtime intact when registration repeats without unload.
- Replace successful registration stand-ins with the real core context, manager, discovered mount and token middleware.
- Assert the owning provider and required scopes, including foreign-route refusal with working own-route controls.
- Keep the ten-second revoke window unchanged. A longer window is possible with the bound gate and is outside this change.
- Build CI's one Ubuntu/macOS matrix from Hermes 0.23.1 and the public method patch until a release contains the method. Rewrite current support claims; preserve dated history.

## Capabilities

### New capabilities

- `dirtside-token-routes`: Public, provider-bound registration, route closure, credential isolation and user guidance.

### Modified capabilities

None. The root capability inventory is empty; this record supersedes the earlier in-flight token-route change's current support assumptions.

## Impact

Production changes stay in route registration and the replies that depend on it. Protocol 1, dependencies, actor rules, the hook and the read-only `LocalEnvironment` and `EnvironmentConnectionError` imports remain unchanged. `requires_hermes` stays at its current value until the method ships; it is not evidence of support for an older core. No data migration or re-pairing is needed.
