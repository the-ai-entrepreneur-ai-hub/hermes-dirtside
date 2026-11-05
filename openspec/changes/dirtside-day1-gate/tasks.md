# Tasks

## 1. Scaffold

- [x] 1.1 Add package, provider-only registration scaffold, manifest, pytest core path, lint configuration, size check and CI. Verify `hermes plugins doctor . --ci` and `tools/check_sizes.py`.

## 2. Model and protocol

- [x] 2.1 Implement frozen records, canonical envelopes, strict parsers and device replay guard. Pass `tests/test_protocol.py` including `test_envelope_roundtrip`, `test_replay_guard`, `test_wire_bodies`, `test_canonical_stable` and `test_parse_result`.

## 3. Registry

- [x] 3.1 Implement pairing, hashed lookup, revocation and thread-local WAL transactions. Pass `test_pairing_code_lifecycle`, `test_revoke`, `test_relay_key_private` and `test_thread_local_wal`.
- [x] 3.2 Implement durable targets and request log recovery. Pass `test_targets`, `test_request_log` and `test_mark_stale_lost`.

## 4. Relay, environment and signed fake device

- [x] 4.1 Implement the pure policy and executor modules. Pass `test_policy_table`, async stdin, clock and size flush, output cap, timeout and cancellation tests in `tests/test_executor.py`.
- [x] 4.2 Implement single-transition relay and process handle. Pass `test_close_idempotent`, `test_kill_unblocks_wait`, `test_lost_covers_queued`, `test_feed_dedupe`, `test_late_result_410` and `test_revoke_cancels_running`.
- [x] 4.3 Prove bounded lossless output with `test_feed_never_drops`, stopped-reader and cancel-during-feed tests.
- [x] 4.4 Wire the real executor to the relay through signed envelopes and the core environment. Pass `test_roundtrip_fake_device`, `test_result_inline_tail` and `test_multibyte_chunks`.
- [x] 4.5 Prove the drain and natural-exit rules with `test_grandchild_returns` and `test_grandchild_survives`.
- [x] 4.6 Run `test_conformance` for every non-network A15.3 row on macOS, plus `test_spawn_via_env`. Require equal output, return code and final cwd against core local execution.

## 5. Provider and server target

- [x] 5.1 Finish target resolution and provider creation. Pass `test_provider_flags`, `test_resolve_target_table`, `test_offline_fails_closed`, identity fallback and revoked-target tests.
- [x] 5.2 Prove the server target uses core's local environment and preserves pwd/cd behavior with `test_server_target_local`.
- [x] 5.3 Run all acceptance commands, record their exact output and the day-0 answers in the private report, and verify no commits, forbidden new source words, core changes, archives or spec sync.

## Workflow follow-up

- Leave this change active for review. Do not archive or sync main specs in this run.
- Steps 6 to 12 remain outside this change.
