# Proposal

## Why

Hermes needs to keep a conversation on the machine its user chose without changing its terminal or file tools. This gate proves that signed requests, persistent shell state, cancellation and raw output work together before adding a network service or a user interface.

## What Changes

Build architecture steps 1 to 5 and the two device execution modules needed by the in-process fake device. Add the package and manifest, typed protocol, SQLite registry, lossless relay, process handle, environment and target provider, with tests against the main core checkout. Leave the network agent, authentication provider, routes, commands, prompt section, service setup and Desktop work for steps 6 to 12.

## Capabilities

### New Capabilities

- `dirtside-protocol`: signed envelopes, strict body parsing and replay protection.
- `dirtside-registry`: pairing credentials, device targets, relay key and request log.
- `dirtside-relay`: live request ownership, output feed and terminal transitions.
- `dirtside-environment`: core-compatible shell execution and file-tool conformance.
- `dirtside-provider`: per-conversation target resolution and server behavior.
- `dirtside-executor`: device policy, process groups, stdin and bounded byte streaming.

### Modified Capabilities

## Impact

- New Python package requiring Python 3.11 or newer and `pynacl>=1.5,<2`.
- Main core checkout is read-only, with no core overrides.
- Plugin registers only a terminal environment provider in this gate.
- No network listener, external platform writes, commits or branches.
