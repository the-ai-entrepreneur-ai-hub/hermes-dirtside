# Scoped token-route registration

## Why

Use only the public context method and fail closed if it is missing or registration cannot succeed. The seam-only change supersedes the original fallback design.

Review point, verbatim (2026-11-08):

1. [auth.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L5) imports `hermes_cli.dashboard_auth.token_auth.register_token_route` and [calls it](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L49-L51) to add your device routes to core's private token-route set. That isn't part of the public plugin API, and there's no `ctx` route for it yet. Please open a hermes-agent issue or PR for a `ctx`-level token-route registration, ideally bound to the provider that registers it (closed #87462 covered this ground). The entry has to wait for that seam, then switch to it.

## What changes

- Add tests/test_review_token_routes.py with exact seam calls, forbidden fallback, unload disposal, mid-registration failure and None refusal.
- Register only through the public method, with an instance-owned fail-closed gate, rollback and unload; pass ctx from registration.
- Test device/local cross-credentials through the real bound gate, with gate-on and gate-off controls.

## Capabilities

### New capabilities
- `dirtside-review-token-routes`: The requirements and executable scenarios in this change.

### Modified capabilities
None.

## Impact

Plugin modules, tests and documentation change without changing signed device protocol version 1 or dependencies.

## Live runtime rebinding

Make existing mounted routers follow successful provider replacement, preserve live relay state through forced rediscovery, and keep real disable/refusal closed without requiring a restart.

## Versioned runtime continuity

Carry live runtime state only from an explicitly compatible versioned provider. Make cached owner environments use the Client while their route gate is retired; accept terminal outcomes from retained module generations by state value. Agents retry generic authentication errors instead of stopping permanently on disable.

## Bounded worker replay

Client execution and stream attachment retry an owner's pre-handler 401 within three seconds, retaining request id and owner. Real-loader cases exercise registration positions 1, 5 and 9, including actual stream attachment.

## Revoke exit

Retain paired credentials for proof-first revocation on every signed route, even when no poll is open. Keep active registry authority separate and preserve same-owner ids by archiving old keys and token hashes with their first revoke time, or replacement time if active. Pairing an already revoked name never starts a new window for its old credential. Keep the agent's exact-body rule and real signed HTTP, subprocess, upload, invalid/replay, restart and replacement checks.

Retained credentials require routes enabled, all public handles active and the ten-second window from the credential's first revoke or replacement. The window follows the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window reopens it, and setting it forward closes it early. Every qualifying signed request inside the window receives the stop, including retries after a lost answer or parked poll. Devices offline or backing off beyond the window keep retrying until manually stopped. A retained principal authorizes nothing inside Dirtside or on foreign bound routes. Legacy unbound routes skip Dirtside while it has a bound policy; closed registrations still prevent recognition after the last policy is gone. A longer window is possible on the bound gate and is not part of this version.

Invalid proof never receives the explicit stop answer; bad retained proof and unknown bearers have different generic bodies inside the window. Restart empties the replay cache, so a captured message younger than 300 seconds can be replayed and receive the stop. Credentials replaced before this version were not retained and need manual shutdown. Use core's own generic rejection for the late-device control. Runtime version 2 refreshes Registry and Relay when the previous provider is version 1, and preserves a same-path version 2 runtime.
