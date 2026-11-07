# Proposal

## Why

A live conversation switched devices after changing directory, and the next device received the first device's directory from core's conversation cwd record. Per-target delegates already own separate shell snapshots, but that record overrides their own cwd before execution.

## What Changes

- Keep working directory and exported-variable state separate for each target within a conversation.
- Restore the selected target's cwd record before terminal planning; select the live cwd for relative file operations.
- Start a newly visited device at its home and restore its state when revisited, including switches through server.
- Preserve core's local server behavior, explicit workdirs and existing missing-directory failures.
- Add real-core target-switch conformance coverage in both in-process and client transports.
- Retain transition history across facade eviction in a provider-owned 1,024-conversation LRU, require contact before device bootstrap and keep unavailable-device cwd metadata reads safe.
- Keep slow delegate bootstrap outside the provider lock, make optional temp-directory lookup safe and recover live delegate cwd after history eviction.
- Document the rule and adjust only the provider or environment budgets actually required.

## Capabilities

### New Capabilities

- `target-shell-state`: Working directory and exported-variable state belong to a conversation and its resolved target.

### Modified Capabilities

None. There are no archived main specs; the active day-7 owner/client requirements remain unchanged.

## Impact

The conversation facade, its existing delegates, real-core test rig, conformance tests, README and architecture documentation are in scope. The pinned core's cwd accessors may be used without editing or rebinding core. No new dependency, command, device protocol field, wire version, commit or deployment is needed.
