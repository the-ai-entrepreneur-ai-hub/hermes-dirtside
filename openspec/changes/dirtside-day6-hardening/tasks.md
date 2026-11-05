# Tasks

## 1. Delivery and trust boundary

- [x] 1.1 Prove dropped-response recovery, running acknowledgement and chunk non-requeue regressions red, then implement optional signed running lists and verify those tests green.
- [x] 1.2 Prove saturated polls block chunk/result delivery, separate the pools and verify feed latency under one second; record the 64-device ceiling in the report.
- [x] 1.3 Prove a three-second feed triggers retries, align phase timeouts with the feed bound and deadline, and verify single uploads and no cancellation.
- [x] 1.4 Prove signed poll replay is accepted, add the shared gateway guard, update exact replay documentation and verify replay returns 400 while newly signed retries stay idempotent.

## 2. Device and environment lifecycle

- [x] 2.1 Prove foreign 401 cancellation and restart-policy regressions, recognize only plugin revocation bodies, and verify successful revoke exit and both rendered service policies.
- [x] 2.2 Prove spawn/lost reasons are hidden and device-cap timeouts wait too long, fix rendering without losing bounded capture or spill metadata and verify exact reasons, suffix and prompt return.
- [x] 2.3 Prove cleanup leaves snapshots, add bounded best-effort device removal and verify snapshot/temp variants disappear and offline/error cleanup stays harmless.
- [x] 2.4 Prove unknown probes access the registry, restrict lazy dispatch resolution and verify optional probes have no reads while target switching still works.
- [x] 2.5 Prove re-pairing breaks stored choices, rotate credentials on the existing id and verify the selected conversation executes without choosing again and rejects old credentials.

## 3. Admission and CI

- [x] 3.1 Run the pinned catalog private-import validator, use public auth exports, remove the unsupported manifest field and add catalog validation to CI; verify the manifest and remaining import inventory.
- [x] 3.2 Add a report-only benchmark threshold flag and CI invocation, verify misses still print and return success only in that mode, and retain failure on command or byte-integrity errors.

## 4. Integration evidence

- [x] 4.1 Run every requested acceptance check, record exact outputs and justified minimal budget deviations in the private report, and verify unchanged Git history with no archive.
