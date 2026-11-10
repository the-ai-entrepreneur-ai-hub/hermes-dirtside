# Design

## Context

See proposal.md for motivation. At ff8dd21 the executor reads 65,536 bytes and immediately posts at that size. Uploads are synchronous. The registry logs submit and terminal transitions only. Lost outcomes use 124 in the relay, handle, stream client, local routes and restart cleanup. Core 84a0301 attaches terminal hints only to 124, 126 and 137.

## Goals / Non-Goals

**Goals:** Change the existing shared boundaries rather than introduce another transport or state machine. Preserve first-byte flushing, backpressure, exact validation and all timeout ownership.

**Non-Goals:** No parallel upload window, gateway reordering, compression, extra device thread, cap increase, core patch or live-install changes.

## Decisions

### Coalesce in the existing executor

Add PART_MAX = 2 << 20 while retaining CHUNK_BYTES for pipe reads and local framing. Accumulate pending bytes until PART_MAX or the existing first-byte FLUSH_MS deadline. Keep the final unsent tail in the result. Clamp the read wait to the next flush deadline so the 100 ms select slice cannot defer small output. The same synchronous send callback retains one in-flight upload and ordered sequence numbers. The loop requires no new queue or concurrency.

64 MiB / 2 MiB = 32 round trips. At 0.7 s that is 22.4 s. Base64 makes 67,108,864 raw bytes approximately 89,478,528 wire bytes, taking 35.79 s at 20,000,000 bits/s. Total is approximately 58.19 s, leaving 61.81 s under 120 s for execution, signing, verification, pipe delivery, headers and variation. One MiB would cost 80.59 s before processing; four MiB would reduce travel further but double each bounded part. Two MiB is enough without pipelining.

### Bound decoded data and both output HTTP inputs

Use PART_MAX in the shared parser, preserving ProtocolError("output part too large"). Bound streamed POST /device/chunk bytes before JSON parsing at 4 * ceil(PART_MAX / 3) + 1024 = 2,797,228. Bound POST /device/result at 2,798,252 bytes, allowing another 1,024 bytes for outcome fields and reason. Count bytes from the stream, not only Content-Length. Keep credential recognition before body reads and all existing signature, identity and ownership checks. Oversized HTTP input returns 413 with the same size reason; malformed decoded parts retain the existing HTTP 400 boundary.

After the bounded read, use the existing worker executor for JSON parsing, canonical signature verification, identity checks, touch and body parsing in their original order. No large JSON, signature or base64 work runs on the dashboard event loop. Concurrent polling must answer while maximum-part verification or parsing is held in a worker. Do not add a concurrent-post 409: same-sequence retries remain serialized and deduplicated by the existing relay writer.

The existing nonblocking pipe writer consumes a memoryview of one decoded part. Trim the old pane tail before extending it with only the last 4,096 incoming bytes, never copying the entire large part into the pane tail. Do not retain body JSON after the parsed part returns. Base64/envelope parsing allocations are bounded by the HTTP input limit. Wire version stays 1 because the fields and signing shape are unchanged; both ends need the larger bound deployed for large parts.

### Keep the kill measurement independent of batching

The benchmark waits for the handle's RUNNING claim rather than a nonempty pane tail before starting its cancellation clock. The command and 50 ms gate stay unchanged. This avoids moving cancellation from the first 64 KiB read into core's longer adaptive poll slots after a 200 ms flush. Record the original 13.34 ms, the uncorrected 42.56 ms and the corrected measurement.

### Size remote matrix time to the measured path

The owner's corrected remote run still stopped at 110.86 s because the rig waited 90 s for a command carrying a 120 s timeout. Its Mac download bottleneck was 1.14 MB/s, not the original assumed 20 Mbit/s upload. Core.call therefore waits timeout + 15 when its args carry a timeout, retaining its existing 90 s default otherwise.

With an external gateway URL, create one owned probe rig before all rows. Pair its remote worker, warm the connection with a small signed chunk, then time a small chunk and one PART_MAX raw-byte chunk, base64-encoded, through the configured public URL. Use an unused request id and require HTTP 410: authentication, verification and decoding run, but no command receives data. No new production or probe route is needed. Time prepared posts so client signing is excluded. Derive base64 bytes per second from the large post's duration minus the warmed small round trip when that difference is positive; otherwise use the positive upload duration alone. Separate fast-loopback samples can be dominated by round-trip jitter. Keep the worker's existing three attempts, accepting its last sample if no upload duration exceeds its round trip. Reject nonfinite or nonpositive upload durations, invalid rates and nonfinite or negative round trips, not their valid relative ordering. Do not substitute a fixed remote budget.

For the default 64 MiB flood, encode each part separately, including base64 padding: 89,478,528 bytes over 32 parts. The remote command timeout is max(120, ceil(1.5 * encoded_bytes / measured_bytes_per_second + 32 * round_trip_s + 10)). At 1,140,000 bytes/s and 0.7 s this is 151 s, with a 166 s rig wait. Do not cap this arithmetic or change core/device policy limits. Loopback does not probe and still carries timeout=120 with the exact existing flood assertions and detail.

Cache the measurement for every row rig. Save a separate probe transcript and prepend the measurement and budget to remote flood evidence, including failures. Its successful detail also reports rate, round trip, budget and command elapsed time. Probe failure fails the run before rows and releases its owned rig. Tests cover arithmetic, wait arguments, the remote worker path, once-only probing, evidence on failures and unchanged loopback behavior.

### Keep hosted benchmark smoke non-gating

The workflow intentionally invokes the benchmark with --report-only. The real subprocess smoke must do the same: require exit zero, the full summary, the four measured rows and two report-only client rows, not four PASS verdicts. Keep the strict benchmark defaults, LIMITS, exact threshold unit tests, byte-integrity checks, cancellation behavior and README gates unchanged. Retain coverage showing report-only ignores timing misses but not execution or integrity errors. No plugin tests or timing bounds change.

### Persist running at the existing claim

Add a registry update conditioned on state='queued' and invoke it beside the handle's RUNNING assignment under the relay condition. This prevents terminal metadata from being overwritten and makes recovered reclaims idempotent. No chunk writes the registry. Terminal state authority remains in relay.close.

### Stop silent orphaned work at the next poll

After a restart, the new owner has terminal stale-history rows but no live handles for old work. A ticking command stops on a refused chunk; a silent command can otherwise run until its device deadline. In Relay.next, inside the condition immediately after _recover, add every reported running id absent from self.handles to that device's existing cancel set. Known queued or running handles are never cancelled by this rule. A legacy poll with running=None adds nothing. No registry query or write is needed, and a repeated running report repeats the cancel until the device drops the id.

Keep the matrix's existing ticking gateway-restart checks unchanged. Add a second phase that writes its shell pid to a private marker without stdout, then execs sleep 600 with timeout=600. An independent command reads and removes the marker before the restart; the target's pane tail must still be empty. Start the cessation clock when the replacement owner is ready and require online contact and the sleeper's disappearance within POLL_HOLD_S + 10, currently 35 s, rather than its 601 s device backstop. Check the stale row is lost/255 with gateway restarted, pairing survives and a fresh command works. Keep eight matrix rows.

Tests cover unknown ids with and without terminal history, known live states, legacy and empty reports, repeated cancels, deduplication and no registry writes. Exercise the real two-phase row before and after the relay fix. Document next-poll cancellation and retain the device deadline only as the unreachable-gateway backstop. Raise only the relay's needed line budget.

Full acceptance exposed a revocation race: immediate orphan replies can leave no parked poll when the credential is removed. Generic core {"error":"unauthenticated","detail":"Unauthorized"} is not proof of revocation and remains retryable. Retained paired credentials permit proof-first verification on polls and uploads. Recognition uses the ten-second window from the credential's first revoke or replacement while routes are enabled. The window follows the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window reopens it, and setting it forward closes it early. Every qualifying signed request inside it gets the stop. Missing that window while offline or backing off means generic retries until manual stop. The day-8 control uses an unknown bearer and core's real response, not a rewritten response.

Pairing an already revoked name never starts a new window for the old credential. Pre-version replaced credentials were not retained, so old processes need manual shutdown. A retained principal authorizes nothing inside Dirtside and cannot authorize a foreign bound route. Legacy unbound routes skip Dirtside while it has a bound policy. A longer window is possible on the bound gate and is outside this change. Keep the exact-body rule, five-second assertions and core middleware unchanged.

Invalid proof never receives the explicit stop answer. Inside the window a bad retained proof has a different generic body from an unknown bearer. Restart empties the replay cache: a captured message younger than 300 seconds can be replayed and receive the stop answer inside the persisted window.

### Change only lost exit codes

Change all production LOST constructors and stale-history cleanup from 124 to 255 without changing reasons. Update only loss assertions and loss fixtures in tests and the matrix, recording every old and new value. Leave timeout branches, assertions, policy refusals, cancellation and A16.4 rendering intact. Add core terminal coverage proving loss has no timeout advice.

## Risks / Trade-offs

- Larger parts increase bounded signing/parsing memory. Mitigation: 2 MiB cap, explicit streamed body cap, one upload and a 4,096-byte tail with no part-sized relay copy.
- First-byte batching can delay a quiet command. Mitigation: preserve the 200 ms deadline and test both the boundary clock and actual read-wait selection.
- Old gateways reject larger parts. Mitigation: document that both ends need this update; no silent wire version or shape change.
- Internet timing is not certified by loopback. Mitigation: retain all eight loopback rows, the 8 MB/s benchmark gate and the owner's pending internet rerun.

## Migration Plan

No schema migration is needed. Deploy the same package on gateway and device, then let the owner rerun the two-machine matrix. Rollback restores the previous package on both ends; stored queued, running and lost state strings remain compatible.
