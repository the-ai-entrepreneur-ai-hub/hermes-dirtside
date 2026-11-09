# Scoped token-route registration

## Why

Use the requested public seam when core offers it and fail closed if registration is refused.

Review point, verbatim (2026-11-08):

1. [auth.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L5) imports `hermes_cli.dashboard_auth.token_auth.register_token_route` and [calls it](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L49-L51) to add your device routes to core's private token-route set. That isn't part of the public plugin API, and there's no `ctx` route for it yet. Please open a hermes-agent issue or PR for a `ctx`-level token-route registration, ideally bound to the provider that registers it (closed #87462 covered this ground). The entry has to wait for that seam, then switch to it.

## What changes

- Add tests/test_review_token_routes.py with exact seam calls, forbidden fallback, unload disposal, mid-registration failure and None refusal.
- Run the new file against pristine 0ae9359, keeping the red log.
- Implement lazy fallback, instance-owned fail-closed gate, rollback and unload; pass ctx from registration.
- Test device/local cross-credentials with seam and fallback, gate on and off; run released-core real flows.
- Run package and fast suites, record green output and exact budget changes, then save WP4 checkpoints.

## Capabilities

### New capabilities
- `dirtside-review-token-routes`: The requirements and executable scenarios in this change.

### Modified capabilities
None.

## Impact

Only this plugin work tree, tests, documentation and private review notes. Keep signed device protocol version 1, requires_hermes >=0.22.7, and existing dependencies. No core edits, archive, commit or network writes.

## Correction 1

Make existing mounted routers follow successful provider replacement, preserve live relay state through forced rediscovery, and keep real disable/refusal closed without requiring a restart.

## Correction 2

Carry live runtime state only from an explicitly compatible versioned provider. Make cached owner environments use the Client while their route gate is retired; accept terminal outcomes from retained module generations by state value. Agents retry generic authentication errors instead of stopping permanently on disable.

## Correction 4

Preserve client execution and stream attachment through the short disposed/new-disabled registration window. Retry only its exact pre-handler 401 within three seconds, retaining request id and owner; observe real stream attachment before reloading.
