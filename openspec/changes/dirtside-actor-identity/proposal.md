# Proposal

## Why

Hermes 0.23.1 separates the current turn's actor from its delivery route. Authorizing the route can deny an owner or retain the first sender's authority. A sender-less turn with a named route must not silently fall back from a device default while the model still expects the device. With an empty route, the plugin's listed-surface default exception remains, even in a constructed merge.

## What Changes

- Read the actor only where a module-presence probe for two published API names indicates binding, checked against the actual public reader without gating that test; otherwise use the bound route user without consulting an environment actor. An empty actor beside a named route is missing identity before host or cron rules.
- Preserve local provenance, owner privileges, no-user host and cron exceptions, direct-Python rules and implicit server defaults.
- Refuse an empty identity with a named route on every platform wherever a chosen or captured default device applies, without server execution. With an empty route, refuse except on the plugin's eleven listed surfaces. Keep known non-owner and listed empty-route default fallback. Disclose server execution where core calls the hook at turn start, not through an invented mid-turn update.
- Identify the no-sender refusal by its exception type so status says no device applies without reading the sender again. Keep other refusal handling, including an unpaired default beside an invalid sender.
- Build relay-local test contexts with the real core type and add shared-turn, real turn-loop, merged/default-turn, queued follow-up, command, host and planted child-environment regressions.
- Add Ubuntu and macOS release gates without changing the pinned-core job. Describe all three checked cores and why any multi-sender shared conversation with a device target is unsafe on the older cores.

## Capabilities

### New Capabilities

- `dirtside-actor-authority`: Current-actor device ownership across shared turns and compatible route-user fallback.

### Modified Capabilities

None. The main specification inventory is empty; earlier ownership changes remain historical change specifications.

## Impact

Production changes are limited to `dirtside/access.py`, the sender-less route/platform guard in `dirtside/provider.py`, the server line in `dirtside/awareness.py` and missing-sender status in `dirtside/commands.py`. Commands, terminal and file dispatch, target awareness, frozen prompt sections and worker IPC share the sender authority. Tests remove inherited session and cron variables at startup. Protocol 1, dependencies, minimum Hermes version, registered hooks, revoke behavior, default capture, known-sender and listed empty-route fallback, and the three transitional private imports remain unchanged.
