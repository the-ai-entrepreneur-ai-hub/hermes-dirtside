# Proposal

## Why

The execution and network paths work, but users cannot yet select devices in chat or inspect work in Desktop. Explicit server selection also needs its own persisted value so it cannot restore a device default.

## What Changes

- Store conversation targets as `server` or a device id, preserving existing device choices.
- Add the five slash-command forms and the bounded, session-frozen target prompt section.
- Make target changes affect the next command despite core's environment cache.
- Ship an uncompiled Desktop pane and target chip using the existing REST routes.
- Add a signed loopback benchmark with enforced latency, throughput and cancellation targets.
- Write installation, pairing, security and measured-results documentation.
- **BREAKING**: replace the internal target reader with `target`; clearing a target restores the configured default rather than selecting server.

## Capabilities

### New Capabilities

- `dirtside-commands`: conversation target selection, device listing, pairing and revocation.
- `dirtside-prompt`: bounded target facts frozen into a new session's prompt.
- `dirtside-desktop`: focused-conversation controls, device status and live request tails.
- `dirtside-bench`: reproducible signed loopback measurements and failure thresholds.

### Modified Capabilities

None.

## Impact

Registry schema, provider, registration, dashboard target routes, core test rig, command/prompt/Desktop/benchmark files, tests and README. No core edits, extra dependency, events, settings page or service operation.
