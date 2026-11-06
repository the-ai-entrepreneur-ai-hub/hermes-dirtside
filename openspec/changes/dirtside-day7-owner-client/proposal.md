# Proposal

## Why

CLI, TUI, Desktop, web chat and slash workers load separate plugin instances, but devices poll the instance mounted in the gateway or dashboard. Their private relays cannot see that device or dispatch to it, despite sharing the SQLite target selection.
The day-7 addendum also reports a cached environment retaining another conversation's identity across turns.

## What Changes

- Keep live relay state only in the process receiving device traffic. Multiple servers may mount the API; only device routes publish the private owner record.
- Give workers a thin authenticated loopback client for execution, streaming, cancellation and device state. Preserve core's handle and deadline behavior.
- Mint one private local secret and enforce mapped-aware loopback peers, fixed token routes, pid start identity and bounded, strictly parsed local request bodies.
- Move stale-request cleanup out of worker registration. Forward worker revocation to the owner.
- Resolve conversation identity and cron context at dispatch, with isolated per-conversation delegates and creation-key fallback only when no current session is named.
- Show bounded, credential-redacted pairing refusal details and the public-host configuration hint for the verified core Host refusal.
- Forward pane state, live tails and revocation from secondary servers. Missing or dead owners mean offline; live-owner transport and HTTP failures stay distinct.
- Test separate processes, run every conformance row in both modes, measure client overhead without a new timing gate, and fix the remote matrix worker's import order.
- Document the verified process model and the measured size budgets.

## Capabilities

### New Capabilities

- `owner-client`: Single-owner relay execution and authenticated local worker access, including discovery, liveness and failure behavior.

### Modified Capabilities

None. Main specifications have not yet been synchronized from the earlier changes.

## Impact

Plugin registration, registry credentials, relay streaming, environment transport, provider dispatch, CLI errors, commands, prompt facts and plugin API routes change. Test rigs, conformance tests, benchmarks and architecture documentation change with them. Device protocol version 1, pane JSON shapes, core code and dependency declarations stay unchanged. No real Hermes home, service manager, external platform or Git history is modified.
