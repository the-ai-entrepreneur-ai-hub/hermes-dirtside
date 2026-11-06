# Proposal

## Why

The internet matrix's 64 MiB output row cannot finish in 120 seconds when every 64 KiB costs a 0.7 second round trip. Live checks also found queued history for claimed commands and timeout advice for lost commands.

## What Changes

- Coalesce pending device output into parts up to 2 MiB, retaining the 200 ms first-byte flush and one ordered upload at a time.
- Enforce the decoded part limit and streamed HTTP chunk/result body limits covering base64 and their signed envelopes. Run JSON parsing, verification and output decoding in existing worker threads. Keep the relay's pipe feed lossless and its pane tail bounded.
- Persist running at claim without per-chunk history writes.
- Report every lost outcome as exit 255 without changing its reason. Keep actual timeout 124, policy refusal 126 and cancellation 130.
- Update README and architecture, preserve all existing checks and record before/after evidence. Trigger the kill benchmark at claim rather than first output so batching does not move it into a longer core poll slot. Leave the internet flood measurement pending the owner's rerun.
- Measure one maximum-part upload and a small round trip from the remote device before matrix rows, derive the remote flood budget from that link, and retain the fixed 120 s loopback row. Rig calls carrying a command timeout wait that timeout plus 15 s for core's outcome.
- Cancel reported running ids absent from the owner's live handles in the same poll reply, without rewriting terminal history or inferring work from legacy polls. Keep the ticking gateway-restart phase and add a silent 600 s sleeper that must stop within one poll interval plus 10 s of the replacement owner becoming ready. Preserve revocation when a fresh poll is rejected by core before reaching the plugin by recognizing core's exact structured 401, not a generic foreign 401.

## Capabilities

### New Capabilities

The main specification inventory is empty. These capabilities document the existing boundaries and their changed requirements:

- `output-delivery`: bounded, ordered device output with interactive flushing and slow-link bulk delivery.
- `request-lifecycle`: truthful claim history and distinct terminal outcome codes.

### Modified Capabilities

None.

## Impact

Touches the shared model/protocol, device executor, relay/registry, chunk/result routes and lost outcomes in the owner/client/environment/local stream. Tests, benchmark, matrix expectations, size budgets, README and architecture follow the same boundaries. Protocol version remains 1 because message fields do not change. No core edits, new dependencies, device upload concurrency/reordering, output-cap increase, timeout-ownership change, live-install access or Git-history changes are in scope.
