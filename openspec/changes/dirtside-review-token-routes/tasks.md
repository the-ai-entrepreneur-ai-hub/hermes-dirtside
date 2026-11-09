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
