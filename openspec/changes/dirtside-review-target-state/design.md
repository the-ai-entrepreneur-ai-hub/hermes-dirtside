# Design

## Context and evidence

Core 84a0301 tools/terminal_tool.py:249-289 owns the mutable conversation cwd record; 351-352 writes workspace overrides, 1041-1061 prefers the record for the next command, and 1219-1220 uses it during environment creation. tools/terminal_tool_result.py:215-225 writes only an observed non-transient result. File tools use it for creation at tools/file_tools.py:281-284, but use the live facade's cwd for relative operations. Idle cleanup deletes environments, not the record (tools/terminal_tool_lifecycle.py). Merely removing writes would let the previous target's directory poison the next command and re-created environments.

Correction to the brief: ctx.session_cwd is NOT a read of that terminal record. hermes_cli/plugins.py:597-600 delegates to plugin_session.py:33-40, which reads agent.runtime_cwd.scoped_session_cwd or policy/workspace config, not tools.terminal_tool. Use ctx only to seed server state; never pretend it recovers the terminal record.

Retain plugin-owned bounded conversation history and per-target delegates, update saved cwds from each delegate's execute result, and create devices at their home. Use public ctx.register_middleware('tool_execution', ...) (plugins.py:939-944; website/docs/developer-guide/middleware.md:53-55,73-76) to bind whether terminal workdir was explicitly supplied. The facade uses its own target cwd for implicit terminal calls and preserves explicit workdir for transient calls, without path guessing or private table access. Direct environment calls still accept cwd normally. The real-core rig runs the same core middleware runner around its terminal entry, matching real tool dispatch. Snapshots remain separate delegate artifacts and follow environment lifetime; cwd history survives idle cleanup. No new runtime dependency or protocol change.

Server still calls core's LocalEnvironment in one lazy factory, with a one-line pending-local-seam comment. The documented subclass example (terminal-environment-plugin.md:147-160) is not a public handoff factory and neither validator publishes that import. Keep EnvironmentConnectionError imported only in environment.py: core terminal_tool.py:1451-1468,1596-1597 renders it as a degraded environment rather than executing locally; request documentation in the provider contract. Latest 8d7061f retains these cwd/execution contracts; ctx moves to plugins_context.py.

Rejected: reset in slash handlers misses pane switches and reaping; ignore all cwd arguments loses explicit workdir; compare against old paths is ambiguous; rebuild local execution loses core's scrub and process behavior; mutate core tables violates the review. Existing day-9 files test_target_state_provider.py and test_target_state_conformance.py stay unedited.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_no_terminal_internals`: Public target state.
- `test_gateway_target_roundtrips`: Stable target round trips.
- `test_switch_after_idle_cleanup`: Idle continuity.
- `test_server_environment_control`: Core local control.
- `test_target_switch_restores_cwd_and_exports`: Day-9 compatibility.
