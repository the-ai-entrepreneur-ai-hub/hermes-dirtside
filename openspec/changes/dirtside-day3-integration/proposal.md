# Proposal

## Why

The existing suite proves the isolated transport, not a user installation selected by Hermes. The remaining checks must exercise startup discovery, backend selection, dashboard authentication and the normal tools together.

## What Changes

- Test an enabled directory installation through startup discovery and the plugin CLI.
- Compare terminal and file tool results with the local backend using a paired subprocess device and the real gated dashboard; file paths remain subject to gateway-side resolution.
- Test device credentials and dashboard sessions on every plugin route.
- Add idempotent user-service installation, removal and dry-run rendering.
- Add a repeatable eight-row reliability matrix with private transcripts and a managed loopback rig.
- Fix integration defects only when these checks reproduce them.

## Capabilities

### New Capabilities

- `dirtside-core-integration`: installed plugin discovery, tool execution and dashboard authentication.
- `dirtside-service-install`: persistent per-user device services on macOS and Linux.
- `dirtside-reliability-script`: repeatable fault checks and saved evidence.

### Modified Capabilities

None. The earlier changes remain active and main specs have not been synchronized.

## Impact

Changes are confined to this plugin's tests, device CLI, demonstrated execution defects and reliability tooling. No core edits, new dependencies, target-schema changes, desktop changes or changes to the other builder's files. The change stays active without archive or spec sync.
