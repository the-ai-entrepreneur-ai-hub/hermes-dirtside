# Tasks

## 1. Slow-link output

- [x] 1.1 Coalesce pending bytes up to PART_MAX with the existing flush deadline; verify a 64 MiB flood uses at most 32 parts and 100 bytes flush by FLUSH_MS.
- [x] 1.2 Enforce decoded and streamed chunk-body bounds and keep the pane tail bounded; verify exact-bound acceptance, oversized refusal, misleading or absent length and byte-exact pipe delivery.
- [x] 1.3 Update README Numbers and architecture A8, A10, A16.x and one Part B note; verify arithmetic, version 1 compatibility and the pending owner-rerun cell.

## 2. Truthful request states

- [x] 2.1 Persist running at claim with an idempotent registry update; verify silent claimed work is running, unclaimed work is queued and chunks make no history writes.
- [x] 2.2 Change every lost outcome to 255 and only its loss expectations; verify original reason strings, preserved partial bytes and no core timeout hint.
- [x] 2.3 Update architecture exit codes and claim history; verify every changed existing loss assertion is listed old-to-new in the private report and timeout assertions are unchanged.

## 3. Integrated acceptance

- [x] 3.1 Set only minimum needed module budgets and run pytest, ruff, sizes, strict OpenSpec validation, doctor and clean-snapshot catalog validation; record exact outputs and any retries.
- [x] 3.2 Run the loopback matrix and after benchmark; verify 8 of 8, at least 8 MB/s and unchanged history count 16.
- [x] 3.3 Finish .notes/delegate/20261106-dirtside-day8/REPORT.md with file:line evidence, bounds, budgets, arithmetic, assertion changes and every check output; leave the change unarchived, live installs untouched and Git history unchanged.

## 4. Correction 1

- [x] 4.1 Trigger the benchmark kill at RUNNING without changing its command or gate; test independence from first output and record all three kill measurements.
- [x] 4.2 Bound streamed result bodies and move signed-message JSON, verification and parsing off the event loop; test maximum results, overflow, concurrent polling and overlapping same-sequence retries.
- [x] 4.3 Correct README's upload assumption, architecture bounds and report citations; state the per-post memory bound and minimum budgets.
- [x] 4.4 Rerun every acceptance check, keep history at 16 and append the exact outputs and remaining limits under Correction 1 in the private report.

## 5. Correction 2

- [x] 5.1 Make rig waits exceed carried command timeouts by 15 s; test timeout outcomes and the unchanged 90 s default.
- [x] 5.2 Measure the remote device path once before rows, derive and record the flood budget, and test arithmetic, public-URL posts, worker execution, cached measurement, failure evidence and unchanged loopback behavior.
- [x] 5.3 Update README and the matrix architecture note without changing the pending cell, loopback row, assertions or production limits; state budgets.
- [x] 5.4 Rerun acceptance, retain 16 commits and append Correction 2 with file:line evidence, test names and exact check outputs.

## 6. Correction 3

- [x] 6.1 Cancel unknown reported running ids inside Relay.next after recovery without touching history or legacy behavior; verify known states, repeated reports and no registry writes.
- [x] 6.2 Keep the ticking restart phase and add a silent sleep 600 with timeout=600; reproduce the failure and prove cessation within one poll interval plus 10 s through the real row.
- [x] 6.3 Document next-poll cancellation and unreachable-gateway backstop, check README restart wording and set only the minimum relay budget.
- [x] 6.4 Preserve revocation after immediate orphan replies by recognizing only core's exact structured 401; test the real middleware boundary and unchanged foreign-401 retries without loosening the existing five-second check.
- [x] 6.5 Rerun all acceptance, keep 16 commits and append Correction 3 with file:line evidence, test names, budgets and exact check outputs.

## Workflow follow-up

- The owner reruns the real two-machine matrix and replaces the pending README flood measurement with the result.
- Do not archive this change in this run.
