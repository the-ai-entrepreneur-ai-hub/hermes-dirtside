# Provider-bound device token routes

## Why

Catalog admission needs token routes registered through the public context method, not core's private route set. Prepare this version for the first Hermes release containing that method, without changing the device protocol or actor rules.

## What changes

- **BREAKING:** Require `ctx.register_dashboard_token_route` for all four device and five local paths. Older Hermes loads the plugin with those routes closed.
- Keep atomic rollback and unload disposal. Explain a missing method, a refusal or a failure in the warning and route-dependent replies, without exposing exception contents.
- Recognize no credentials while routes are disabled or a public route handle is inactive, including on other token routes, and keep an already enabled runtime intact when registration repeats without unload.
- Give senders who may pair the closure reason when selecting, listing or using devices. A closed owner acts locally and can still revoke and cancel live work.
- Replay pre-handler local execution and stream 401s within the existing three-second bound, preserving request identity.
- Replace successful registration stand-ins with the real core context, manager, discovered mount and token middleware.
- Assert the owning provider and required scopes, including foreign-route refusal with working own-route controls.
- Keep the ten-second revoke window unchanged. A longer window is possible with the bound gate and is not part of this version.
- CI's one Ubuntu/macOS matrix fetches Hermes 0.23.1 and the exact public method commit with its parent, then applies their difference without `website/*`.

## Capabilities

### New capabilities

- `dirtside-token-routes`: Public, provider-bound registration, route closure, credential isolation and user guidance.

### Modified capabilities

None. The root capability inventory is empty; this record supersedes the earlier in-flight token-route change's current support assumptions.

## Impact

Production changes stay in route registration, recognition, worker retries and route-dependent replies. Protocol 1, dependencies, actor rules, the hook and the read-only `LocalEnvironment` and `EnvironmentConnectionError` imports remain unchanged. The version stays `0.1.0` and `requires_hermes` stays `>=0.22.7`; both move together when a Hermes release has the method. The current floor is not evidence of support for an older core. No data migration or re-pairing is needed.
