# Tasks

## 1. Regression tests

- [x] 1.1 Add tests/test_review_token_routes.py with exact seam calls, forbidden fallback, unload disposal, mid-registration failure and None refusal.

## 2. Red evidence

- [x] 2.1 Run the new file against pristine 0ae9359, keeping the red log.

## 3. Implementation

- [x] 3.1 Implement lazy fallback, instance-owned fail-closed gate, rollback and unload; pass ctx from registration.

## 4. Integration and disclosure

- [x] 4.1 Test device/local cross-credentials with seam and fallback, gate on and off; run released-core real flows.

## 5. Validation and checkpoint

- [x] 5.1 Run package and fast suites, record green output and exact budget changes, then save WP4 checkpoints.

## Correction 1

- [x] C1.1 Prove forced-discovery and registry replacement red; bind each request and local handler to the current instance while preserving live relay state.
- [x] C1.2 Verify real disable/re-enable, partial refusal, in-flight work and both transports without opening unloaded routes.

## Correction 2

- [x] C2.1 Prove old-provider upgrade and cached in-process/Client re-enable defects; require a runtime version, route retired relays through Client and refuse unclaimed self-forwarding without changing ordinary reload or secondary forwarding.
- [x] C2.2 Prove retained mounted-generation close and kill defects, then normalize terminal states and compare kill states by value.
- [x] C2.3 Prove disable's generic core 401 stops agents, then retry generic and unknown-credential errors for poll and upload while retaining exact explicit-revoked shutdown.

## Correction 4

- [x] C4.1 Prove exact disabled-route /exec and /stream loss on C3, add bounded same-id retry with strict refusal controls, and wait for actual stream attachment in the real reload test.
- [x] C4.2 Run 20 fresh serial client reload cases per prepared core under measured CPU load, in addition to the whole-file correction repeats.

## Revoke exit

- [x] R1 Add signed route, invalid/replay, offline subprocess, real upload and re-pair regressions; preserve red evidence before the gateway fix.
- [x] R2 Separate retained proof from active authority, archive rotated paired credentials, recheck persisted state and preserve the unchanged agent stop rule and stable same-owner choice.
- [x] R3 Document one ten-second rule and reconcile the earlier parked-poll and generic-401 assumptions.
- [x] R4 Prove the real-core foreign-route exposure, bound recognition to the first ten seconds under either registration API and keep refusal closed.
- [x] R5 Prove independent device clocks, repeated answers, restart, first-event replacement and invalid-proof controls, with bearer-free isolation checks.
- [x] R6 Require runtime version 2, refreshing old version 1 lookups while preserving compatible same-path version 2 state.

Recognition lasts 10 seconds from the credential's first revoke or replacement while routes are enabled. Every qualifying signed request gets the stop inside it. Pairing an already revoked name never reopens the old credential's window. Devices offline or backing off past it keep retrying until manually stopped. The bearer passes other plugins' released core token gates during the window but authorizes nothing inside Dirtside. Invalid proof never receives the explicit stop answer; bad retained proof and unknown bearers have different generic bodies. A restart empties the replay cache, so a captured message younger than 300 seconds can receive the stop inside the window. Pre-version replaced credentials need manual shutdown.
