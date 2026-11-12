# Tasks

## 1. Slow-link output

- [x] 1.1 Coalescing retains the first-byte deadline and sends a 64 MiB flood in at most 32 parts.
- [x] 1.2 Decoded parts, streamed request bodies and the pane tail stay bounded with byte-exact delivery.
- [x] 1.3 Maximum-part parsing and signature verification stay off the dashboard event loop.
- [x] 1.4 Kill timing begins at RUNNING independently of first output.

## 2. Request states and restart

- [x] 2.1 First claim persists running idempotently; chunks never write history.
- [x] 2.2 Lost outcomes use 255 with the same reason and partial bytes, without timeout advice.
- [x] 2.3 Unknown running ids are cancelled on the next poll without affecting known live work or legacy reports.
- [x] 2.4 Ticking and silent restart scenarios retain pairing and stop orphaned work within one poll plus 10 seconds.
- [x] 2.5 Only the exact authenticated revoked answer stops the agent; generic core and foreign 401s keep retrying.

## 3. Link measurement

- [x] 3.1 Rig waits exceed carried command timeouts by 15 seconds, retaining the 90-second default otherwise.
- [x] 3.2 One signed remote probe determines the flood budget with measured rate and round trip.
- [x] 3.3 Fast-link samples retain the finite positive fallback and three-attempt policy.
- [x] 3.4 Report-only benchmark smoke checks all six rows without weakening strict timing or byte-integrity checks.
