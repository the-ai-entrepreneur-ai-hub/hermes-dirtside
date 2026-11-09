# Plugin-owned target state

## Why

Remove terminal_tool coupling while preserving day-9 cwd, exports, file routing and core local execution.

Review point, verbatim (2026-11-08):

3. [provider.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/provider.py#L8) uses `tools.environments.local.LocalEnvironment`, and [`_select`](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/provider.py#L57-L77) reads and writes core's per-session cwd table through `tools.terminal_tool`. Neither is public API. Keep per-target cwd inside the plugin, or ask in a hermes-agent issue for a public "fall back to the local backend" / session-cwd seam.

## What changes

- Add tests/test_review_target_state.py for no terminal imports, task/session mismatch, idle switches, three round trips and core-local credential control.
- Run new tests on a pristine 0ae9359 export and preserve the red output.
- Replace core cwd access in provider.py with plugin history, explicit facade execution and public middleware; isolate the local factory and consolidate the error import.
- Update real-core rig to use core's tool execution middleware path without editing day-9 test files.
- Run all day-9 tests unchanged, package tests and the fast suite; record exact budgets and save WP3 checkpoints.

## Capabilities

### New capabilities
- `dirtside-review-target-state`: The requirements and executable scenarios in this change.

### Modified capabilities
None.

## Impact

Only this plugin work tree, tests, documentation and private review notes. Keep signed device protocol version 1, requires_hermes >=0.22.7, and existing dependencies. No core edits, archive, commit or network writes.

## Correction 1

Remove cleanup's dependency on current-turn identity while keeping all model execution authorized and preserving fixed, bounded snapshot deletion.

## Correction 2

Snapshot the configured default per conversation at first prompt/status/display/dispatch resolution. Existing conversations retain that name across reload and idle recreation; new conversations get the new default. Keep explicit target changes live.

## Correction 4

Narrow device-routing claims to terminal commands and disclose gateway-side file-path resolution. This is documentation of the owner's supplied Mac/WSL2 observation, not a file-path implementation change.
