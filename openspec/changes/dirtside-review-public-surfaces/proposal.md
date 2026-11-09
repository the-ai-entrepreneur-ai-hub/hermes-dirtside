# Public surfaces and disclosure

## Why

Expose only the three unavoidable transitional runtime imports to core's own catalog lint and document the seams honestly.

Review point, verbatim (surface and disclosure follow-up to all points):

1. [auth.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L5) imports `hermes_cli.dashboard_auth.token_auth.register_token_route` and [calls it](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/auth.py#L49-L51) to add your device routes to core's private token-route set. That isn't part of the public plugin API, and there's no `ctx` route for it yet. Please open a hermes-agent issue or PR for a `ctx`-level token-route registration, ideally bound to the provider that registers it (closed #87462 covered this ground). The entry has to wait for that seam, then switch to it.

2. [executor.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/agent/executor.py#L93-L96) runs model-written scripts with no `env=`, so they inherit the device agent's whole environment. `hermes dirtside serve` loads the device's Hermes `.env`, so every provider key there is visible to model commands. Hermes' local backend strips those keys. Pass an explicit minimal env: PATH, HOME, USER, LANG/LC_*, TERM and TMPDIR, plus a passthrough list the user declares in the device policy.

3. [provider.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/provider.py#L8) uses `tools.environments.local.LocalEnvironment`, and [`_select`](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/provider.py#L57-L77) reads and writes core's per-session cwd table through `tools.terminal_tool`. Neither is public API. Keep per-target cwd inside the plugin, or ask in a hermes-agent issue for a public "fall back to the local backend" / session-cwd seam.

- [commands.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/commands.py#L49-L79): paired devices are shared across the whole gateway, so any admitted user can `/dirtside use`, `pair` or `revoke` the owner's device. Bind each device to the sender who paired it, or add an owner allowlist (defaulting to that sender) and check it in all three commands.

## What changes

- Add tests/test_public_surfaces.py using core private_import_findings and a clean git-tracked/current intended export.
- Run that test against pristine 0ae9359 and keep the 29-finding red log.
- Move internal-import dev tooling to tests and update all import paths, CI, matrix and benchmark entry points and exact budgets.
- Write README and architecture rules and the notes-only SEAM-REQUESTS.md; update README test count from pinned collection.
- Run strict OpenSpec, both full core suites, both doctor/clean-export validators, ruff, sizes, pinned matrix and benchmark, and 20 repeats of new/day-9 files; save WP5 checkpoints and REPORT.md.

## Capabilities

### New capabilities
- `dirtside-review-public-surfaces`: The requirements and executable scenarios in this change.

### Modified capabilities
None.

## Impact

Only this plugin work tree, tests, documentation and private review notes. Keep signed device protocol version 1, requires_hermes >=0.22.7, and existing dependencies. No core edits, archive, commit or network writes.

## Correction 1

Disclose frozen shared target facts, gateway-user server execution, pairing availability, preserved re-pair names and exact WSL interop behavior. Record correction red/green evidence and the required two-core gates, five serial repeats and C1 checkpoints.

## Correction 2

Record Correction 2 lifecycle, default-snapshot and revocation decisions with red/green evidence, both-core admission and full-suite checks, strict benchmark, matrix, five serial C1/C2 file-union repeats and cumulative C2 checkpoints.

## Correction 3

Record real native local identity red/green evidence, correct owner-loss test teardown, repeat all C1-C3 changed test/helper files five times and rerun every final gate. Keep the optional server-row optimization out because it would weaken C2's durable server-default snapshot contract without a larger change.

## Correction 4

Correct every core citation across repository documentation, login/Windows authority, safe pairing examples and device file-tool claims. Run the actual unchanged citation checker. Preserve prior report history, add C4 red/green and all gates, five whole-file correction rounds, 20 loaded client reload runs per core, reconstructed C4 checkpoints and inventories since C3 and WP5.
