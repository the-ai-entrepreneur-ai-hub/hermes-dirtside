# Tasks

## 1. Planning gate

- [x] 1.1 Record all five root causes with source lines, finish the timeout delta and validate `dirtside-day5-linux --strict` before editing implementation or tests.

## 2. Timeout ownership

- [x] 2.1 Add device-first, empty-output, ordinary-exit-124 and bounded-capture regressions; demonstrate the missing device-first suffix on the unchanged implementation.
- [x] 2.2 Share the policy-capped grace duration between execution and upload retries; verify duration boundaries, local backstop termination and retry deadline coverage.
- [x] 2.3 Reuse core's timeout branch for explicit device timeouts, preserve cap/timeout identity and document the contract in architecture; verify exact output, flags, spill metadata and non-timeout terminal outcomes.

## 3. Portable execution tests

- [x] 3.1 Keep a real shell and child in signal tests and replace ordered/sleep-based pool assumptions with acknowledged dispatch and worker readiness; verify both signals, all process-group members and unchanged cancellation bounds.
- [x] 3.2 Finish the all-test portability audit, replace host-specific cwd/fallback paths and scheduling-dependent flush/stop readiness; verify focused tests and record every finding in the report.

## 4. Integration acceptance and handoff

- [x] 4.1 Run full pytest, ruff, size budgets, strict change validation and the isolated plugin doctor; retain exact outputs and fix in-scope failures without skipping tests or weakening assertions.
- [x] 4.2 Review the full diff, confirm unchanged four-commit history and clean core, scan changed files for prohibited names/prose and deliver the private day-5 report with final source lines and Linux limitations.

## Workflow follow-up

- The owner runs GitHub-hosted Ubuntu and returns the exact log if any check fails.
- Leave this change active. Do not commit, push, branch, archive or synchronize it.
