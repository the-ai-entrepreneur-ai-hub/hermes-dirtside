# Design

## Context

See proposal.md for scope and motivation. The read-only target checkout is `../hermes-agent-main`, revision `84a0301415edd6d1385207ec96e4d7f2b6c1fcd9`. All core file references below are relative to that checkout. Both design documents were read in full before any artifacts were written. The private plan remains private.

## Goals / Non-Goals

- Keep the A2 domain types and the A3 import boundary. Tests can import real core file tools, interruption and background-process APIs to exercise their contracts.
- Reuse core wrapping, snapshots, cwd extraction, output capture and interruption. Never copy or replace core functions.
- Prove POSIX behavior on this macOS host with a signed in-process device.
- Do not implement routes, authentication providers, device configuration, the network loop, commands, prompt sections or user interfaces.

## Day-0 verifications

1. **Provider lookup and kind.** Core's `tools/terminal_tool_backends.py`, lines 268 to 288 at `84a0301` sends non-built-in names to `_build_plugin_env`; lines 236 to 249 looks up the registered provider and constructs its environment. Core's `tools/terminal_tool_config.py`, lines 158 to 185 at `84a0301` resolves through `agent.terminal_env_registry.get_provider`. Core's `agent/terminal_env_registry.py`, lines 24 to 45 at `84a0301` reserves built-in names, not community names. Core's `hermes_cli/plugins_registrars.py`, lines 59 to 66, 103 to 128 at `84a0301` has no kind or provenance admission restriction for terminal providers. Core's `hermes_cli/plugins_discovery.py`, lines 301 to 324 at `84a0301` treats backend kind as load policy, not a restriction on other registrations. In-process isolation is mandatory, enforced at core's `tools/terminal_tool_backends.py`, lines 239 to 247 at `84a0301`.

2. **Token route seam and unknown bearer.** Core's `hermes_cli/dashboard_auth/token_auth.py`, lines 31 to 34 at `84a0301` is a public importable function that registers exact paths and has no caller restriction. An isolated import and registration probe succeeded. Lines 49 to 72 tries every token provider; lines 75 to 96 returns 401 for a bearer no provider recognizes, or 503 if none accepts it and a backing provider was unreachable. Community registration can use the seam in step 7. No auth provider or route is registered now.

3. **Session binding.** Core's `gateway/session_context.py`, lines 131 to 159 at `84a0301` sets the key and identifier ContextVars; lines 188 to 194 reads ContextVars before the legacy environment fallback. Core's `gateway/run.py`, lines 3959 to 3989 at `84a0301` binds `context.session_key` at lines 3982, and lines 4007 to 4011 copies context into worker threads. Core's `gateway/run_turn_prepare.py`, lines 654 to 658 at `84a0301` binds before the turn, so environment construction and first prompt rendering inherit it. Slash handlers independently bind a scope at core's `gateway/run_inbound_hooks.py`, lines 269 to 299 at `84a0301`, including worker dispatch. Core's `agent/system_prompt.py`, lines 113 to 134 at `84a0301` calls the section renderer once in the caller's context; core's `hermes_cli/plugins_dispatch.py`, lines 659 to 676 at `84a0301` does not introduce or clear a session scope. Its metadata has a session identifier but no session key (core's `agent/system_prompt.py`, lines 86 to 94 at `84a0301`), so the callable must read the ambient key. Legacy Desktop binds at core's `tui_gateway/server.py`, lines 931 to 950 at `84a0301`; its slash worker exports the key at core's `tui_gateway/slash_worker.py`, line 164 at `84a0301`. Unbound CLI callers can have only an identifier or neither; the provider will not consult an empty shared target key.

4. **Cwd reaching the provider.** Core's `tools/terminal_tool.py`, lines 755 to 765 at `84a0301` accepts declared `~` without host expansion. With `terminal.cwd` unset, lines 775 to 780 keeps `~`. With it set, lines 776 to 780 keeps an absolute path or expands a non-default tilde path on the gateway. Container sanitizing at lines 805 to 809 does not apply because `is_container` is false. Desktop's deliberate project pick wins at core's `tui_gateway/session_workdir.py`, lines 249 to 262 at `84a0301`; task/session cwd wins over configured cwd at core's `tools/terminal_tool.py`, lines 1213 to 1236 at `84a0301`. The plugin receives that path unchanged, not a home fallback. An invalid selected path must fail on the device, not silently change machines or directories.

5. **Payload and persistence.** Core's `tools/environments/base.py`, lines 268 to 272 at `84a0301` declares the stdin modes including payload. At this revision there is no separate payload conditional: lines 703 to 705 embeds only heredoc mode, and lines 727 passes stdin directly to `_run_bash`. Core's `tools/terminal_tool_lifecycle.py`, lines 258 to 270 at `84a0301` keys per-turn persistence on `_session_scoped` or `_persistent`.

6. **Process handle and descriptor.** Core's `tools/environments/base_output.py`, lines 269 to 281 at `84a0301` requires poll, kill, wait, stdout and returncode. Although stdout is annotated as text, lines 371 to 384 gets its descriptor and lines 410 to 429 reads raw bytes with one incremental decoder. A binary `os.pipe` read end is therefore appropriate. Core polls rather than calling wait (core's `tools/environments/base.py`, lines 546 to 581 at `84a0301`). True EOF ends draining immediately; three idle ticks apply when a grandchild holds the writer.

7. **Version and interpreter.** Core's `pyproject.toml`, line 7 at `84a0301` says `0.0.0`; lines 15 supports Python `>=3.11,<3.15`. Core's `hermes_cli/__init__.py`, lines 23 to 39 at `84a0301` yields `0.0.0` without an install stamp. The real version gate uses core's `hermes_cli/plugins_manifest.py`, lines 461 to 465 at `84a0301` and core's `hermes_cli/version_info.py`, lines 240 to 262, 292 to 312 at `84a0301`: this tagless checkout reports base `unknown`, identity `git.84a0301`. The release floor is `requires_hermes: ">=0.22.7"`. Release tag `v0.22.7` (2026-11-03, commit `592aa804d6ed135a18d6a01fb0824bfdbb0279d7`) carries all four required contracts at the same locations as tested main. The following references name the prepared main checkout: payload mode at core's `tools/environments/base.py`, line 272 at `84a0301`, the persistence check at core's `tools/terminal_tool_lifecycle.py`, line 270 at `84a0301`, `register_token_route` at core's `hermes_cli/dashboard_auth/token_auth.py`, line 31 at `84a0301`, and `skip_container_guards` plus `default_cwd` in `agent/terminal_env_provider.py`. The supplied interpreter reports Python 3.14.6, not 3.11. No local interpreter or dependency is changed.

The exact doctor syntax was read once with `hermes plugins doctor --help`: `hermes plugins doctor [-h] [--ci] [target]`.

## Decisions

- Use frozen domain records and strict field schemas, with bool distinct from int, validated base64, identifiers, absolute device paths and bounded chunk lengths. Check signatures before replay state changes or body parsing. The device replay cache is sender-scoped and bounded; the gateway relies on sequence and terminal-state deduplication.
- Use one SQLite connection per thread, WAL, normal synchronous mode and immediate transactions for pairing. Retain revoked identifiers so a chosen device never turns into a server target. Store only hashed bearers and use constant-time comparisons. Minting again invalidates an older pending code for that name.
- Keep all request-state decisions under the relay Condition. Serialize concurrent feeds per handle with the same Condition. Duplicate the nonblocking writer while feeding so close cannot recycle its descriptor underneath a parked writer. Recheck terminal state in bounded select slices. A terminal handle leaves the live map; its waiter retains the terminal outcome. Revoke keeps an in-memory device tombstone to stop racing polls.
- Keep the A2 outcome unchanged. The executor returns `(outcome, optional_tail)`, matching the result parser, because an outcome alone cannot carry the unsent final bytes. Its callback sends only complete streaming chunks. A cancellation Event is the small testable boundary until the network loop owns running executions.
- Run the actual executor in the fake device with signed poll, exec and result envelopes. Enforce a bounded worker pool and authenticate bearer lookup before verification. Do not open HTTP routes just to test transport-independent code.
- Use a thin root `__init__.py` entry point delegating to the package register function with a relative import. Core's directory loader requires the root file (core's `hermes_cli/plugins_loader.py`, lines 808 to 837 at `84a0301`). No extra provider facade is needed.
- Keep the raw command in a ContextVar while calling core execute. Its deadline worker copies the calling context (core's `agent/deadline.py`, lines 329 to 355 at `84a0301`). One shared command attribute would race when two callers execute on the same environment, potentially applying the wrong deny pattern. A real concurrent execution test pins command attribution without serializing core's snapshot behavior.
- Resolve bash through the device PATH before spawning, retaining its absolute argv name. On the tested host core selects `/bin/bash`; passing just `bash` changes missing-command and missing-directory error text. Conformance compares the unmodified output, not a normalized version.
- Report the actual policy byte cap in the truncation reason and render it in the environment. The default remains 64 MiB, and small test policies do not incorrectly claim that 64 MB was returned. Render a policy refusal reason as well.
- For conformance, use real core shell file operations and background process registry calls. Generate random input once and run the same random-output command against the same source file. Use shared controlled cwd and shell environment so differences are not fixture noise. Test every non-network battery row on macOS.
- Use only `default_target` in config_schema. The draft's three timing settings and folder allowlist were explicitly removed by the architecture. Describe the provider and execution privileges without promising later surfaces.

## Deviations from ARCHITECTURE.md

- The version floor is `>=0.22.7`, rather than the draft's `>=0.22.6`. Release `v0.22.7`, commit `592aa804d6ed135a18d6a01fb0824bfdbb0279d7`, contains all four required contracts listed above. A tagless development checkout is not a reason to lower the release floor.
- The configured interpreter is 3.14.6. This is within core's supported range and the plugin's Python 3.11 minimum.
- Payload behavior is direct forwarding at core's `base.py`, line 727 at `84a0301`, not a separate payload branch. The implementation follows that contract.
- A root loader entry point is required in addition to `dirtside/__init__.py`.
- The executor returns the outcome and final chunk together and accepts a cancellation Event. This closes the architecture sketch's missing tail/cancel return channel without changing wire or domain types.
- Empty session identities do not read a shared target record. This prevents unrelated unbound callers from borrowing a device choice.
- The fake device budget covers wiring, not the executor. The two pure device modules are included now as requested; the remaining device agent is deferred.
- A ContextVar replaces the sketch's shared command attribute to prevent concurrent policy misattribution. No new core import or execution serialization is introduced.
- Bash is PATH-resolved, instead of using a bare argv name, for byte-exact diagnostics. Other core shell installations still require conformance on their actual host.
- The truncation notice names the configured cap in bytes rather than hardcoding 64 MB.

## Risks / Trade-offs

- A selected gateway path can be absent on the device. Preserve it and report failure rather than guessing a different cwd.
- Snapshot files are shared within one environment, as in core. Parallel execution on one environment is not serialized by core. This gate does not invent a second session model.
- Clearing an explicit target restores the configured default. With a non-server default, a future command cannot pin server using the current nullable target table. Step 8 must settle that representation before promising an explicit server override.
- A missing default device follows A7 and resolves to server; a missing explicit device fails closed. A stricter default policy needs an owner decision before the command/UI work.
- The device cap can truncate a cwd marker; the environment retains the previous cwd and appends an honest cap notice.
- Network retry, gateway restart and real device death are deferred, not simulated as conformance successes.

## Migration Plan

No existing data or installations are changed. Registration creates private plugin storage, marks stale request rows lost and registers only the provider. All local validation uses a repository-local temporary Hermes home. Removing or disabling the plugin rolls back selection; no core changes need reverting.
