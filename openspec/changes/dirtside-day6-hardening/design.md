# Design

## Context

See proposal.md for motivation. Core evidence is from 84a0301. Separate pools and the gateway replay guard replace the original shared-pool design.

## Goals / Non-Goals

**Goals:** repair the confirmed failure paths with failing-before regression tests, exact boundary parsing, mccabe at most eight and minimal module growth.

**Non-Goals:** another transport, persistent live handles, new dependencies, core patches or sandboxing.

## Decisions

1. Add only `running` to poll bodies. Missing means legacy behavior; an explicit list enables recovery. Under the existing Condition, requeue output-free unacknowledged requests once at poll entry, before claiming. A feed in progress or an abandoned poll prevents recovery. Track accepted requests until result delivery completes.
2. Use a lazy 64-worker poll pool as the online-device ceiling per gateway and an independent 16-worker feed pool for both chunk and result delivery. Do not consume the core default pool for bounded pipe writes.
3. Use phase-specific upload timeouts bounded by the existing device execution deadline. Keep retries sequential and re-sign every attempt.
4. Retain the environment wait adaptation for terminal reasons and early device timeouts. A pipe-only notice cannot safely be written synchronously at close when a reader has stopped, and core has no early-device-timeout rendering hook. Reuse the supplied collector for exact bounded timeout rendering and metadata rather than importing private output helpers.
5. Keep one gateway replay guard on the registered auth provider's shared protocol module. Check signatures and nonces before contact or dispatch; retain sequence idempotence for newly signed retries.
6. Recognize only exact plugin 401 detail bodies. Foreign 401s take the transport backoff path. Successful serve exit combines with launchd `SuccessfulExit: false` and systemd `on-failure`. Do not weaken core token recognition to force a revoke response through a gate that has already rejected it.
7. Cleanup runs an unwrapped, quoted removal command through the device, with a five-second timeout, to avoid recreating the snapshot. Restore a valid device cwd for cleanup and swallow all ordinary failures.
8. Resolve only known work methods on attribute lookup. All other probes and cwd reads consult the last delegate; work still re-resolves the target. Retain cleanup of every cached delegate.
9. Rotate credentials on the previous named identity, consuming the pending row in the same transaction. Prefer the active identity, otherwise the latest previously paired identity, over the pending code's throwaway id. An authenticated replacement may restore that revoked identity. Record the replacement public key under the relay Condition, clear stale presence and reject old parked or queued poll handlers before recovery or dispatch. Serialize commit and key publication in one worker so overlapping pairings cannot publish stale keys.
10. Move auth types to the exported package; inventory unavoidable imports with the pinned admission validator. CI runs catalog validation and a benchmark flag that ignores only threshold misses, never execution or data-integrity failures.

## Risks / Trade-offs

- Recovery cannot prove exactly-once execution across a whole device-agent crash before output. The guarantee is for a sequential poll loop that knows its accepted ids, as requested.
- Legacy agents omit `running` and do not gain recovery until upgraded.
- The replay cache is bounded to 4,096 nonces and 300 seconds, not durable replay storage.
- A foreign gate 401 is indistinguishable from revocation when the plugin handler never runs. Back off rather than kill legitimate commands.
- Best-effort offline cleanup can leave artifacts; reconnecting cleanup is not a background job.
- Shared-runner benchmark timing is noisy. CI prints threshold status without making it a timing gate; data-integrity failures still fail.

## Migration Plan

Deploy the gateway and device together for recovery. Version 1 and empty legacy poll bodies remain accepted. Regenerate already installed service units with `install-service`. No schema migration is needed.
