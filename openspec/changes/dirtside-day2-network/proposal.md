# Proposal

## Why

The provider gate executes against an in-process device only. A device on another machine needs authenticated pairing, signed HTTP transport and a foreground agent before the backend can be used remotely.

## What Changes

- Add private device configuration, a keep-alive poll loop, bounded execution, retrying uploads and signal shutdown.
- Add a token-only dashboard auth provider and single-use signed pairing.
- Add four device routes and dashboard-session routes for devices, targets, requests, pairing and revocation.
- Add pair, serve and status CLI commands and a module entry point.
- Exercise the real core, real HTTP and subprocess failure cases without changing core.

## Capabilities

### New Capabilities

- `dirtside-agent-loop`: authenticated device dispatch, uploads, cancellation and recovery.
- `dirtside-auth`: token recognition and single-use device pairing.
- `dirtside-routes`: device protocol boundaries and dashboard controls.
- `dirtside-cli`: private pairing configuration and foreground device commands.

### Modified Capabilities

None. The day-1 change remains active and main specifications remain untouched.

## Impact

Adds device and dashboard modules and tests. Extends registry read methods and request ownership checks without changing the targets schema or target methods. Uses installed HTTP and dashboard dependencies. Service installation is not part of this network layer.
