# Proposal

## Why

The fresh-context review found delivery, authentication and lifecycle failures in the signed device path. Harden these boundaries against the pinned core without changing protocol version 1 or adding another transport.

## What Changes

- Recover unacknowledged, output-free dispatches using an optional signed poll `running` list.
- Separate parked polls from feeds and align upload timeouts with the relay's feed bound.
- Surface terminal reasons and promptly render device policy timeouts using core's output contract.
- Reject replayed device envelopes and distinguish plugin revocation from foreign 401 responses.
- Stop service restart loops after deliberate agent exit.
- Remove device snapshots on cleanup, avoid attribute-probe I/O and preserve identity on re-pairing.
- Use public auth exports, run catalog private-import validation in CI, remove the unsupported manifest field and print non-gating benchmark results in CI.

## Capabilities

### New Capabilities

The canonical specification inventory is empty. Reuse the capability paths used by the earlier, unarchived changes:

- `dirtside-relay`: recoverable dispatch, independent feeds and gateway replay rejection.
- `dirtside-agent-loop`: bounded uploads, signed running acknowledgements and deliberate revocation exit.
- `dirtside-environment`: visible reasons, early timeout rendering, cleanup and side-effect-free probes.
- `dirtside-registry`: stable device identity across credential rotation.

### Modified Capabilities

None in the canonical inventory.

## Impact

Touches the relay, protocol boundary, HTTP router, device loop, environment adapters, registry, service rendering, README, manifest and CI. No new dependencies, core edits, architecture edits, Git history changes or archive operation. The private report records regressions, remaining core couplings, exact check outputs and any minimal budget increases.
