# Public surfaces and disclosure

## Why

Expose only the two read-only environment imports to core's catalog lint and document the remaining seams.

Review point, verbatim (surface and disclosure follow-up to all points):

1. [auth.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L5) imports `hermes_cli.dashboard_auth.token_auth.register_token_route` and [calls it](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L49-L51) to add your device routes to core's private token-route set. That isn't part of the public plugin API, and there's no `ctx` route for it yet. Please open a hermes-agent issue or PR for a `ctx`-level token-route registration, ideally bound to the provider that registers it (closed #87462 covered this ground). The entry has to wait for that seam, then switch to it.

2. [executor.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/agent/executor.py#L93-L96) runs model-written scripts with no `env=`, so they inherit the device agent's whole environment. `hermes dirtside serve` loads the device's Hermes `.env`, so every provider key there is visible to model commands. Hermes' local backend strips those keys. Pass an explicit minimal env: PATH, HOME, USER, LANG/LC_*, TERM and TMPDIR, plus a passthrough list the user declares in the device policy.

3. [provider.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/provider.py#L8) uses `tools.environments.local.LocalEnvironment`, and [`_select`](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/provider.py#L57-L77) reads and writes core's per-session cwd table through `tools.terminal_tool`. Neither is public API. Keep per-target cwd inside the plugin, or ask in a hermes-agent issue for a public "fall back to the local backend" / session-cwd seam.

- [commands.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/commands.py#L49-L79): paired devices are shared across the whole gateway, so any admitted user can `/dirtside use`, `pair` or `revoke` the owner's device. Bind each device to the sender who paired it, or add an owner allowlist (defaulting to that sender) and check it in all three commands.

## What changes

- Cover core's private_import_findings on a clean export in tests/test_public_surfaces.py.
- Move internal-import dev tooling to tests and update all import paths, CI, matrix and benchmark entry points and exact budgets.
- Describe trust limits and collected test counts in README and architecture.

## Capabilities

### New capabilities
- `dirtside-review-public-surfaces`: The requirements and executable scenarios in this change.

### Modified capabilities
None.

## Impact

Plugin modules, tests and documentation change without changing signed device protocol version 1 or dependencies.

## Shared prompt and host execution

Disclose frozen shared target facts, gateway-user server execution, pairing availability, preserved re-pair names and exact WSL interop behavior.

## Runtime continuity and defaults

Preserve compatible runtimes and durable default snapshots while retaining proof-first revocation.

## Native identity and retained state

Native CLI/TUI identity and owner-loss cleanup use real core paths. Server rows remain necessary to preserve durable server-default snapshots.

## Login and file-path boundaries

Describe actual login and Windows authority, safe pairing syntax and device file-tool limits, with explicit core source references.

## Descriptor ownership and revocation

Remove the runtime select descriptor ceiling from device reads, relay writes and local streaming without changing timing or output bounds. Real high-descriptor streaming tests and an autouse descriptor guard cover the limit. Test database connections, pipes, retained streams and started LSP services have explicit teardown. Revocation coverage distinguishes authenticated proof from retryable generic 401s and retains the five-second shutdown bound.
