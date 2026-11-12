# Proposal

Actor identity behavior recorded on 2026-11-10. Current route-registration requirements are in dirtside-seam-only-registration.

## Why

Hermes 0.23.1 separates the current turn's actor from its delivery route. Authorizing the route can deny an owner or retain the first sender's authority. A sender-less turn with a named route must not silently fall back from a device default while the model still expects the device. With an empty route, the plugin's listed-surface default exception remains, even in a constructed merge.

## What Changes

- Read the actor only where a module-presence probe for two published API names indicates binding, checked against the actual public reader without gating that test; otherwise use the bound route user without consulting an environment actor. An empty actor beside a named route is missing identity before host or cron rules.
- Preserve local provenance, owner privileges, no-user host and cron exceptions, direct-Python rules and implicit server defaults.
- Refuse an empty identity with a named route on every platform wherever a chosen or captured default device applies, without server execution. With an empty route, refuse except on the plugin's eleven listed surfaces. Keep known non-owner and listed empty-route default fallback. Disclose server execution where core calls the hook at turn start, not through an invented mid-turn update.
- Identify the no-sender refusal by its exception type so status says no device applies without reading the sender again. Keep other refusal handling, including an unpaired default beside an invalid sender.
- Build relay-local test contexts with the real core type and add shared-turn, real turn-loop, merged/default-turn, queued follow-up, command, host and planted child-environment regressions.
- The actor step originally added release CI beside the pinned job. The seam-only change replaces both with one method-core Ubuntu/macOS matrix; older-core device support is not part of this version.

## Capabilities

### New Capabilities

- `dirtside-actor-authority`: Current-actor device ownership across shared turns and compatible route-user fallback.

### Modified Capabilities

None. The main specification inventory is empty; earlier ownership changes remain historical change specifications.

## Impact

Actor identity uses the shared access lookup, sender-less resolver guard, server fact line and typed status refusal. Commands, terminal/file dispatch, awareness, frozen sections and worker IPC share sender authority. Protocol 1, dependencies, hooks, revoke behavior, default capture, known-sender and listed empty-route fallback remain unchanged.
