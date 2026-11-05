# Tasks

## 1. Step 6: device agent

- [x] 1.1 Add private atomic DeviceConfig with home resolution, key and policy validation; pass configuration tests in tests/test_agent.py.
- [x] 1.2 Add the keep-alive loop, signed polls, bounded execution, retrying uploads, cancellation, signals, local log and module entry; pass isolated HTTP loop tests in tests/test_agent.py.
- [x] 1.3 Add CLI parser, serve and local status; pass parser and status tests using the real core CLI attachment helper.

## 2. Step 7: authentication and routes

- [x] 2.1 Add the pure token recognizer and registrations; pass tests/test_auth.py with real core protocol compliance and no mutation.
- [x] 2.2 Add dashboard manifest and all routes, typed request ownership, atomic code-bound pairing and desktop reads; pass tests/test_routes.py under gate on and off, including replay, late posts, pool responsiveness and loader mounting.
- [x] 2.3 Add signed CLI pairing and one-line package registrations; pass real HTTP CLI pairing, pwd, persistent cd, stop and revoke tests.

## 3. Network conformance and final verification

- [x] 3.1 Pass the default-run slow subprocess SIGKILL test with 50-second loss detection, exit 124 and retained partial output.
- [x] 3.2 Pass subprocess failed-chunk retry and gateway-restart tests without duplicated bytes or re-pairing.
- [x] 3.3 Pass subprocess SIGINT/SIGTERM, pinned-key/replay and parallel-cancellation coverage, then run all acceptance checks and write the private report with exact outputs, line counts and registration handoff.

## Workflow follow-up

- Keep the change active. Do not archive or sync main specs.
- Leave all work uncommitted and preserve the other builder's owned files.
