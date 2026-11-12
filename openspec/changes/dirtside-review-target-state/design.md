# Design

## Context and evidence

Pinned core's `tools/terminal_tool.py`, lines 249 to 289 at `84a0301` owns the mutable conversation cwd record; 351-352 writes workspace overrides, 1041-1061 prefers the record for the next command, and 1219-1220 uses it during environment creation. Core's `tools/terminal_tool_result.py`, lines 215 to 225 at `84a0301` writes only an observed non-transient result. File tools use it for creation at core's `tools/file_tools.py`, lines 281 to 284 at `84a0301`, but use the live facade's cwd for relative operations. Idle cleanup deletes environments, not the record (tools/terminal_tool_lifecycle.py). Merely removing writes would let the previous target's directory poison the next command and re-created environments.

ctx.session_cwd is not a read of that terminal record. Core's `hermes_cli/plugins.py`, lines 597 to 600 at `84a0301` delegates to core's `plugin_session.py`, lines 33 to 40 at `84a0301`, which reads agent.runtime_cwd.scoped_session_cwd or policy/workspace config, not tools.terminal_tool. It seeds server state rather than recovering the terminal record.

Retain plugin-owned bounded conversation history and per-target delegates, update saved cwds from each delegate's execute result, and create devices at their home. Use public ctx.register_middleware('tool_execution', ...) (core's `plugins.py`, lines 939 to 944 at `84a0301`; core's `website/docs/developer-guide/middleware.md`, lines 53 to 55, 73 to 76 at `84a0301`) to bind whether terminal workdir was explicitly supplied. The facade uses its own target cwd for implicit terminal calls and preserves explicit workdir for transient calls, without path guessing or private table access. Direct environment calls still accept cwd normally. The real-core rig runs the same core middleware runner around its terminal entry, matching real tool dispatch. Snapshots remain separate delegate artifacts and follow environment lifetime; cwd history survives idle cleanup. No new runtime dependency or protocol change.

Server still calls core's LocalEnvironment in one lazy factory, with a one-line pending-local-seam comment. The documented subclass example (core's `terminal-environment-plugin.md`, lines 147 to 160 at `84a0301`) is not a public handoff factory and neither validator publishes that import. Keep EnvironmentConnectionError imported only in environment.py: core's `terminal_tool.py`, lines 1451 to 1468, 1596 to 1597 at `84a0301` renders it as a degraded environment rather than executing locally; request documentation in the provider contract. Latest 8d7061f retains these cwd/execution contracts; ctx moves to plugins_context.py.

Rejected: reset in slash handlers misses pane switches and reaping; ignoring all cwd arguments loses explicit workdir; comparing old paths is ambiguous; rebuilding local execution loses core's scrub and process behavior; mutating core tables relies on private state.

## Regression coverage

- `test_no_terminal_internals`: Public target state.
- `test_execution_middleware_matches_manifest`: Core's capability probe and provides_middleware declare the same tool_execution callback.
- `test_gateway_target_roundtrips`: Stable target round trips.
- `test_switch_after_idle_cleanup`: Idle continuity.
- `test_server_environment_control`: Core local control.
- `test_target_switch_restores_cwd_and_exports`: Day-9 compatibility.

## Context-free snapshot cleanup

Core's `tools/terminal_tool_lifecycle.py`, lines 135 to 176 at `84a0301` and cleanup_all_environments invoke cleanup without a turn's sender context. The adapter's cleanup sends only its internally constructed, quoted snapshot removal with an empty model preview, bound to the recorded device owner. It bypasses no model-command authorization: execute/_run_bash still require the current sender, and the serving relay still checks the cleanup request's owner. It never calls execute or accepts a model script. test_context_free_cleanup_removes_only_its_snapshot covers idle and shutdown cleanup from an explicit empty Context thread for local and messaging ownership.

## Durable conversation defaults

Use a session_defaults table in the plugin's existing SQLite registry with an insert-if-absent transaction. Store the configured name, including server, not mutable authorization or online facts. resolve_target consults it for non-cron conversations before resolving the target. This shares one snapshot across frozen prompt rendering, cached facades, idle recreation, Desktop and workers, and survives disable/re-enable without a global cache. Every call still checks the current sender and device row. Explicit choices override the snapshot; clearing one returns to the conversation's snapshot. Existing pre-upgrade conversations acquire their snapshot at their first resolution under this version; already frozen prompt bytes cannot be reconstructed or rewritten.

## Gateway-resolved file paths

Core resolves file paths on the gateway; terminal commands perform device edits without that path conversion. On 2026-11-09 the owner observed an absolute read working while a write parent resolved on the Mac. That observation was not independently reproduced by the shared-disk rig.
