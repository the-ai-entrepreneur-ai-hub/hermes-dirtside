# Tasks

## Proof and implementation

- [x] Trace core and propose this change before implementation.
- [x] Prove `test_termux_detection_and_environment` red on the base and green after implementation.
- [x] Prove `test_other_platform_environment_unchanged` red on the base and green after implementation.
- [x] Prove `test_termux_default_names_exclude_secrets` red on the base and green after implementation.
- [x] Owner-run scratch harness passed signed pairing, shebang/Python/PREFIX, exit 7, cancel 130 and revoke in a real aarch64 Termux userland, Python 3.14.10 and PyNaCl 1.6.2.
- [x] Copy the owner's passing harness, retaining its context, system user, writable Termux tmp, ownership fix, default apt source, readiness wait and before/after native PyNaCl comparison.
- [x] Owner reran `bash scripts/termux_check.sh` on the final tree and passed. The builder executes no Docker. Physical phone, mobile network and Termux:API remain untested.
- [x] Prove `test_pairing_reports_termux` and `test_termux_loopback_forward` red on the base and green after implementation.
- [x] Finish documentation and line budgets.
- [x] Save tracked diff and untracked checkpoint, leave the change unarchived.
