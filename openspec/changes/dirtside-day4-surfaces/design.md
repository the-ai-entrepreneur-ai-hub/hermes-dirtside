# Design

## Context

See proposal.md for scope. Core is pinned to `84a0301415edd6d1385207ec96e4d7f2b6c1fcd9`. Existing routes already expose device facts and live 4,096-byte request tails. Core caches terminal environments and freezes prompt sections for a session.

## Goals / Non-Goals

Goals: one target representation across all surfaces, no silent local fallback, measured claims and no build step.

Non-goals: core changes, model tools, events, a settings page, folder confinement, physical-host or Desktop runtime certification.

## Decisions

1. **Targets.** Store `target TEXT NOT NULL` without a device foreign key, because `server` is not a device. Migrate the old table transactionally, copying device ids and timestamps. `None` deletes a row; `server` persists. Validate new selections against paired devices. Resolution checks the explicit choice before cron/default rules and fails closed on a removed chosen device. Keep the six existing truth-table rows and add explicit server over macbook.
2. **Cached execution.** A provider-owned conversation adapter resolves before each command and delegates to ordinary local/device environments. It keeps separate snapshots per target, uses a lock for delegate creation, and keeps filesystem access through shell operations so a cached local file adapter cannot bypass a later device selection. In-flight commands keep their original delegate. Core's recorded conversation cwd still crosses targets: its execute boundary does not distinguish an explicit workdir from the recorded cwd (core's `tools/terminal_tool.py`, lines 1014 to 1061, 1373 at `84a0301`). Preserve it rather than guess; document an explicit workdir when that path is absent on the new device. Rejected alternative: importing core cwd/cache internals, outside A3's imports.
3. **Commands.** Bind one sync text handler to ctx, registry, relay and configured default. Use `session_identity()` for conversation writes, online choices plus server for the picker, single-use minting for pair, and both registry/relay revocation. Validate arity, names and absent session identity. Pair replies use `--code=<value>` and a user-filled `<gateway-url>`, not a guessed endpoint.
4. **Prompt.** Bind `current_target_section(session_info)` through a small instance. Prefer bound session identity, then the supplied session id when unbound. Look up target facts without requiring online contact; do not replace a missing selected device with the default. JSON-quote bounded facts so device strings remain data. Core owns freezing; never invalidate its prompt.
5. **Desktop.** Plain ESM uses only the SDK, React and jsx-runtime. React Query owns polling and error state. Devices/requests poll every 2 seconds only while the contributed pane is visible. Queries are connection/profile/activation/session scoped. Read the focused durable session key, not its unrelated runtime id; disable writes when the focused owner differs from the REST helper's active route. Refetch/invalidate after writes, never optimistically claim success. Show failures instead of stale target success.
6. **Benchmark.** Temporary private homes, supplied core checkout, real LocalEnvironment versus signed FakeDevice and DirtsideEnvironment. Warm both, collect 50 paired pwd samples, report nearest-rank p50/p95 of remote-minus-local durations, verify exactly 10,000,000 output bytes with capture unbounded, and measure kill-to-return after a running execute call emits a full chunk. Exit nonzero on any missed threshold. This measures in-process signed loopback, not HTTP or LAN. Measurements exposed the executor's fixed 100 ms EOF-before-exit sleep; replace it with a bounded 10 ms process wait. Cancellation is sampled early, not after the 200 ms partial-output flush. Core's adaptive sleep can delay later cancellation by up to 200 ms; this benchmark does not certify that case or physical process cessation.
7. **README.** Measurements carry their date and source revision, with the day-3 8/8 matrix attributed separately. There is no folder sandbox, fixed retry count, full-command device log or script-hash audit.

### Verified core calls and paths

Paths below are relative to the pinned core checkout, inspected on 2026-11-05.

| Call / contract | Source |
|---|---|
| `ctx.ask_choice(question, choices) -> str or None` | core's `hermes_cli/plugins.py`, lines 618 to 622 at `84a0301` |
| `ctx.register_command("dirtside", handler, description=..., args_hint="<use|devices|pair|revoke>", argument_mode="text")` | core's `hermes_cli/plugins.py`, lines 649 to 674 at `84a0301` |
| `ctx.register_system_prompt_section("dirtside.target", callable, position="after_memory", max_chars=600)` | core's `hermes_cli/plugins.py`, lines 959 to 984 at `84a0301` |
| Prompt metadata and frozen snapshots | core's `agent/system_prompt.py`, lines 86 to 137 at `84a0301` |
| `ctx.register({id:"pane", area:"panes", title:"Dirtside", data:{placement:"right", width:"320px"}, render})` and chip at `STATUSBAR_AREAS.right` | core's `apps/desktop/src/contrib/plugin.ts`, lines 371 to 400 at `84a0301`, `sdk/areas.ts` |
| `ctx.rest(path, {method, body})`, namespace-relative and profile-aware | core's `apps/desktop/src/contrib/plugin.ts`, line 396 at `84a0301`, core's `api/plugins.ts`, lines 44 to 99 at `84a0301` |
| `useValue(host.state.focusedSessionId)`, focusedStoredSessionId, focusedSessionOwner, connectionId, profile | core's `apps/desktop/src/sdk/index.ts`, lines 560 to 610 at `84a0301` |
| `useValue(host.paneVisibility("dirtside:pane"))` | core's `apps/desktop/src/sdk/index.ts`, line 1299 at `84a0301`; saved SDK host API |
| `useQuery`, `useQueryClient`, `useGatewayActivationEpoch`, `useValue`, `StatusDot({tone})` | core's `apps/desktop/src/sdk/index.ts`, lines 1695, 1897, 1977 to 1981 at `84a0301`; `components/status-dot.tsx` |
| `desktop/plugin.js` unified-package discovery, no Desktop manifest needed | core's `apps/desktop/electron/desktop-plugins-root.ts`, lines 220 to 230 at `84a0301`; core's `desktop-plugin-install.ts`, lines 222 to 232 at `84a0301` |
| Stored session_key differs from runtime session_id | core's `tui_gateway/methods_session.py`, lines 372, 427 at `84a0301`; context binding core's `tui_gateway/server.py`, lines 931 to 950 at `84a0301` |

The existing hidden `dashboard/manifest.json` already declares the backend. Keep it; adding a dashboard JS entry would incorrectly claim a web-dashboard UI.

## Risks / Trade-offs

- Frozen target facts become stale after a mid-session switch. Command replies and pane explicitly name next-command behavior; a new session refreshes the prompt.
- Device and request fields are untrusted display text. Render text nodes only; never HTML or executable strings.
- The REST helper routes to the active gateway, not an arbitrary focused owner. Refuse mismatched-owner writes rather than selecting another conversation.
- Signed in-process measurements exclude HTTP/proxy latency. Label the table accordingly; do not claim LAN or internet performance.
- The conversation adapter changes the concrete cached type and keeps server file operations on the shell path. Test actual terminal/file behavior and persistence, not a bare-class identity.

## Migration Plan

On first registry open, rebuild only the legacy targets table under the existing write transaction. Preserve pairings, request history and target timestamps. Restart the gateway after updating the Python half; enable the opt-in Desktop half separately. Older versions cannot read the new target column, so rollback requires restoring a database backup rather than guessing a device for explicit server rows.
