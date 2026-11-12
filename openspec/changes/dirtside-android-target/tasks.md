# Tasks

## Platform behavior

- [x] Termux detection and measured system names have regression coverage.
- [x] Other platforms retain their original environment allowlist.
- [x] Secret-shaped names are excluded from Termux defaults.
- [x] Signed pairing reports Android (Termux), and the loopback forward preserves body and response bytes.

## Measured lifecycle

- [x] On 2026-11-08 the signed lifecycle check passed pairing, shebang/Python/PREFIX, exit 7, cancel 130 and revoke in aarch64 Termux with Python 3.14.10 and PyNaCl 1.6.2.
- [x] The harness preserves the system user, writable tmp, ownership fix, default apt source, readiness wait and before/after native PyNaCl comparison.
- [x] The owner's rerun of `bash scripts/termux_check.sh` passed. Physical phones, mobile networks and Termux:API remain untested.
