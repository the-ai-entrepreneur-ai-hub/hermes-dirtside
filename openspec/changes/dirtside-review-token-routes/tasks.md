# Tasks

Historical record through acceptance on 2026-11-10. Current support and verification follow dirtside-seam-only-registration; earlier checked items do not claim new verification.

## 1. Regression tests

- [x] 1.1 Add tests/test_review_token_routes.py with exact seam calls, forbidden fallback, unload disposal, mid-registration failure and None refusal.

## 2. Red evidence

- [x] 2.1 Run the new file against pristine 0ae9359, keeping the red log.

## 3. Implementation

- [x] 3.1 Historical (2026-11-08): implemented the then-required registration fallback and instance-owned rollback/unload. The seam-only change removes that fallback.

## 4. Integration and disclosure

- [x] 4.1 Historical (2026-11-08): tested both earlier registration paths and released-core flows. Current coverage uses the real public method only.

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
- [x] R4 Historical (accepted 2026-11-10): proved released-core foreign-route exposure and the original ten-second bound. The seam-only change migrates those assertions to bound-gate refusal with positive controls.
- [x] R5 Prove independent device clocks, repeated answers, restart, replacement without moving the original window and invalid-proof controls, with bearer-free isolation checks.
- [x] R6 Require runtime version 2, refreshing old version 1 lookups while preserving compatible same-path version 2 state.

Recognition uses the unchanged ten-second window from first revoke or replacement while routes are enabled. The whole-second gateway clock can reopen or close it after a clock change. Every qualifying signed request inside it gets the stop; late devices keep retrying until manually stopped. Foreign bound routes refuse Dirtside credentials, and legacy unbound routes skip Dirtside while it has a bound policy. A longer window is possible on the bound gate and is outside this change. Invalid proof never receives the explicit stop answer. Restart empties the replay cache; pre-version replacement credentials need manual shutdown.
