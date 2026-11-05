# Design

## Context

See proposal.md for motivation and the timeout delta for the behavior contract. Evidence below refers to plugin HEAD `fd625cf` and read-only core `84a0301`, before implementation. Architecture A5, A6, A9, A15 R3/R4/R10 and A16 through A16.3 govern the change.

| Failure | Source evidence and root cause |
|---|---|
| `test_conformance_timeout` | `tests/test_conformance.py:20-24,66-73` compares exact local and device output. `dirtside/agent/executor.py:71` and `dirtside/agent/loop.py:55` independently use the requested deadline. Core `tools/environments/base.py:549,569-576,605-606` checks exit before its deadline branch and treats a completed device timeout as a normal exit. `dirtside/environment.py:79-83` only adds refusal/cap notices. A device-first result therefore loses the suffix and timeout flag. |
| `test_timeout_retains_partial_and_kills_device_process` | `tests/test_environment.py:104-114` reaches the same executor/environment race and requires the exact missing suffix. This is the same defect, not a separate partial-output loss. |
| `test_subprocess_signal_stops_entire_group[2]` | `tests/test_network.py:47,51-52` ends its shell script with a simple `sleep` and assumes at least two descendants including bash. A shell may replace itself with that final command. Linux can therefore produce the observed single-member group without a cancellation defect. |
| `test_subprocess_signal_stops_entire_group[15]` | The same command and count assertion, parametrized at `tests/test_network.py:41`. Both signals need a real multi-member group, not a weaker assertion. |
| `test_parallel_limit_keeps_poll_cancellation_live` | `tests/test_network.py:70-78` assumes workers 1 and 2 start first, waits for the second shell to have a child, then sleeps 300 ms to infer saturation. The predicate at line 75 can never succeed after shell replacement. `tests/network_support.py:29-35` explains the generic five-second error. Slow scheduling is an additional risk, not the established primary cause. |

The executor also overwrites a timeout reason with its cap notice (`dirtside/agent/executor.py:107-110`), which would hide timeout identity even after normalizing ordinary device-first timeouts. Upload expiry is converted separately in `dirtside/agent/loop.py:61-62`; both paths must retain that identity.

## Goals / Non-Goals

**Goals:** Preserve exact local timeout semantics, raw bytes, bounded capture, policy caps, cancellation and whole-group signal coverage. Keep all A3 budgets, mccabe 8 and existing core-import restrictions.

**Non-Goals:** Change core, add wire fields, redesign the executor pool, certify Linux without running it, change performance targets, skip tests, or alter service managers and real user state.

## Decisions

### One capped backstop duration

Add one pure domain calculation for `min(requested + 1, policy.max_timeout_s)`. Both executor drain and chunk retry expiry consume it. One second exceeds core's maximum 200 ms adaptive polling interval (`tools/environments/base.py:579-581`) while keeping a disconnected device bounded. Policy always wins. Do not extend only the drain: a blocked chunk callback would still stop at the old deadline.

### Reuse the real core timeout branch

Core embeds the suffix directly in `_wait_for_process`; `_finalize_wait_result` only assembles output and spill metadata (`tools/environments/base_output.py:199-206`). There is no exported suffix formatter.

Use a wait-only handle view whose `poll` treats only a finished, exit-124, explicit device-timeout outcome as still pending. All other attributes and outcomes delegate unchanged. Core then runs its own deadline branch, renders its own suffix, preserves capture metadata and sets its own flag. Raw handle `poll` and `wait` still report the actual terminal state. The environment does not copy text, reconstruct rendered output, import output internals or patch core.

A device policy can stop the process before the requested gateway deadline. The tool can wait the remaining caller budget for core's timeout rendering, but the device process cannot continue during that wait. This is preferable to duplicating core's formatter or adding fragile introspection. Gateway cancellation still closes immediately.

When a cap and another termination coincide, preserve the termination reason first and append the cap notice after `; `. Match the exact first reason, not just exit 124 or arbitrary output. The environment displays the cap component separately. Upload-deadline conversion preserves that component too.

### Prove concurrency by observed events

End signal-test scripts with `sleep 60; :`, so bash must remain to execute a builtin after the child. Wait for a real multi-member group before signalling and keep the existing count, all-members-dead and five-second cessation assertions.

For parallelism, use a poll-observed Event after all three requests have been acknowledged, plus PID-file readiness from the actual two workers. Select whichever two started, cancel one, and wait for the previously queued worker. No scheduling-order assumption or fixed readiness sleep remains. Readiness deadlines are at least ten seconds; existing cancellation latency assertions remain five seconds.

### Portability audit

- Use the sibling checkout as `conftest.py`'s fallback, not a user-specific absolute macOS path (`conftest.py:9-12`).
- Replace incidental `cd /tmp` tests with quoted fixture directories, including one containing spaces. Keep exact cwd and recovery-trailer assertions (`tests/test_conformance.py:30`, `tests/test_core_terminal.py:28,40,56,101-103`, `tests/test_core_surfaces.py:23,28`). Synthetic protocol `/tmp` fields do not access the host and stay unchanged.
- Replace the flush test's 500 ms sleep and scheduling-dependent 150-450 ms interval (`tests/test_executor.py:74-83`) with exact controlled-clock boundary assertions plus an output-acknowledged child. Replace stop-test readiness sleeps with observed output, retaining exact interruption results.
- Make the background-job delta handshake explicit instead of racing a three-second sleep (`tests/test_conformance.py:175-191`). Pass the random pairing code as `--code=<value>` in the CLI test (`tests/test_cli.py:65`), since a URL-safe code can begin with a dash.
- Inspect all tests and helpers for bash path/version, `ps`/`kill` flags, `readlink -f`, random-data throughput and real timing contracts. Keep PATH bash resolution and POSIX syntax. Existing random-byte conformance uses one pre-generated file; benchmark bytes come from `/dev/zero`, not random-device throughput.
- Keep genuine performance and loss/cancellation bounds unchanged. The Linux runner must still meet them; no blanket timeout or threshold widening is permitted.

### Correction 1: CI scratch and background log acknowledgement

The owner's workflow run `42100714688` on `a927f83` passes all 262 tests on Ubuntu, then fails doctor staging. The macOS job exposes an incomplete background-log handshake.

Core defaults scratch to `HERMES_HOME/cache/scratch` (`hermes_bootstrap.py:456-466`). Doctor creates its temporary staging directory there and refuses overlap with the plugin source (`hermes_cli/plugin_dev.py:31-56,68-78`). Set home, runtime and TMPDIR under `runner.temp` in the acceptance step's environment, where the runner context is supported, and create those directories before checks. The runner context is unavailable in job-level environment expressions. Doctor must still stage the actual checkout. `conftest.py:12-24` remains the sole owner of pytest state: it overrides inherited home, runtime, HOME and temporary settings only within pytest and its children, not the parent shell or subsequent doctor process.

Core's environment poller reads a log delta, appends it, then checks process liveness (`tools/process_registry.py:1427-1458,1460-1471`). On exit it finishes and returns without another log read. `read_log` only reads the retained buffer (`tools/process_registry.py:2017-2045`), so waiting after exit cannot recover a missed final delta. No Dirtside log-path defect is established.

The test command prints each fragment and waits for its own file acknowledgement. Release the first gate after observing `first`, and the exit gate only after the registry reports exact `firstsecond`. Then require exit 7 and the exact retained log as before. Reuse the existing conditional file-poll interval, without a fixed readiness sleep. A 30-second readiness deadline allows the extra core poll on a busy runner. Clean up both gates and any unfinished owned job. No production or core code changes are needed for this correction.

## Risks / Trade-offs

- A very busy gateway can still lose the deadline race despite the grace. Explicit device-timeout normalization makes the visible result independent of that race.
- Policy-capped early timeout rendering can wait until the requested gateway deadline. Execution remains stopped at the stricter cap.
- POSIX child reaping differs across hosts. Keep real process/group assertions and report Linux as unverified until the owner runs CI.
- Day-4 benchmark thresholds run on real hardware. Retain them without retrying away slow samples or weakening limits.

## Migration Plan

Validate all planning artifacts strictly before code. Add deterministic regressions, implement the change, run focused checks, then run the five acceptance checks and verify unchanged history. Update architecture and write the private report with exact outputs and final file:line evidence. No database, manifest or protocol migration is needed. Leave the change active and unsynchronized.
