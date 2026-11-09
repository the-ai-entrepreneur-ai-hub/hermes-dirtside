# Design

## Context

See proposal.md for motivation. In core 84a0301, core's `tools/environments/base.py`, lines 312 to 327 at `84a0301` stores cwd and a unique snapshot path on each environment. Core's `base_session_env.py`, lines 183 to 202 at `84a0301` sources and updates that file. The existing per-conversation, per-target delegates already separate snapshots.

There is a second cwd store: core's `tools/terminal_tool.py`, lines 249 to 283 at `84a0301` records one directory per conversation. Its resolver at 1014-1061 reads that record before the call at 1373-1376 passes cwd explicitly to the delegate. Merely choosing a different delegate or changing the outer cwd getter does not remove this override.

## Goals / Non-Goals

**Goals:** Preserve the existing delegates and shell snapshots while restoring the selected target's own cwd before core resolves a command. Keep local server behavior, explicit workdirs, file operations and existing failures intact.

**Non-Goals:** No core edits, runtime rebinds, protocol changes, new transport, new command or new persistence across process restarts.

## Decisions

1. On the terminal path, activate the conversation's facade when core reads the provider's `default_cwd` during configuration (core's `tools/terminal_tool.py`, lines 755 to 776 at `84a0301`), before its planner reads the conversation cwd record at 1220. File tools with a live facade select through its `cwd` getter instead. A weak per-conversation index finds live facades without extending their lifetime. Unknown attribute probes, including absent `host_cwd`, remain registry-free and raise AttributeError normally, including on an uninitialized facade.
2. Keep the selected identity and per-target durable cwds on the provider, not on an evictable facade. Save the outgoing core record only on a real transition; a recreated facade on the same target leaves the surviving core record untouched and uses it for its new delegate. Retain server's initial cwd separately from a later device-derived command plan. Keep at most 1,024 conversation entries, touching their insertion order at selection and removing the least recently used entry when over the cap. This history contains no facades or snapshots. Do not copy, concatenate or clear snapshot contents.
3. Keep server on `LocalEnvironment` and preserve its configured initial cwd. New device delegates start at their own home. Explicit per-command workdirs remain core-owned rather than being turned into persistent target state.
4. Never probe for directory existence or heal a deleted cwd. The original wrapper and failure rendering remain authoritative.
5. Extend the real-core rig to own and close two fake devices. Run the switch conformance through the owner and a separate client worker. Hide A's fixture directory while B runs, then restore it before returning to A, modeling disjoint device filesystems without patching core.
6. Require online contact before constructing any device delegate, even from metadata selection, so a swallowed offline bootstrap cannot be cached. Keep execution fail-closed. The cwd getter catches the existing connection error and returns the last known directory for unavailable or revoked selections.
7. Serialize delegate creation with the facade's own lock. Hold the provider lock only while reading or updating transition history and the weak index, never across bootstrap. Re-read history after bootstrap because other conversations can evict it during that wait. If a live delegate outlasts its history, restore its cwd rather than the reconstructed server seed.
8. Define `get_temp_dir` on the facade so optional attribute lookup is registry-free; resolve the selected delegate only when the method is called, inside core's existing fail-soft boundary. Other core optional probes are concrete facade attributes, the guarded cwd getter or absent on both supported delegates.

Resetting only in the slash command was rejected because pane choices and context-derived target changes must also work. Ignoring every supplied cwd was rejected because it discards explicit workdirs. Recreating environments on every switch was rejected because it loses exports and prior directories.

## Risks / Trade-offs

- Private core cwd accessors can change between releases; document the seam and pin the real-core regression to the supplied checkout.
- Metadata selection must happen before cwd resolution, not only when execute is looked up; exercise terminal-first and file-first switches.
- A transient workdir must not become the stored cwd; compare the server path with core's local behavior.
- Core reaping removes delegates and snapshots but deliberately leaves its cwd record. Test same-target recreation and a target change during that gap in both transports. Provider history survives reaping, not process restart or eviction beyond its 1,024-conversation LRU cap.
- A foreground result completing after a target switch can still rewrite the shared conversation cwd record; document this parallel-completion ceiling without changing code.
- Only raise provider or environment line budgets to the delivered size if necessary; keep complexity at eight and protocol version at one.

## Migration Plan

The owner installs the eventual committed update and restarts the gateway and conversation workers. Existing running environments are not migrated. Rollback is an owner-managed source rollback and restart; no registry or device data migration is involved.
