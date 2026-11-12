# Design

## Context and evidence

Core's `website/docs/getting-started/termux.md`, lines 9 to 10 at `84a0301`, says its Termux package is broken. The base `dirtside/agent/executor.py` child_environment allowlist removes Termux system names. Termux's python-pynacl package build declares 1.6.2. Both cores accept the existing os string in the same version-1 hello.

## Decision and rejected alternatives

The small platform module uses names measured from the real image, rejects secret-shaped defaults and preserves non-Termux behavior and explicit policy passthrough.

On 2026-11-08 a signed lifecycle check passed pairing, terminal commands, exit
codes, cancel and revoke in aarch64 Termux with Python 3.14.10 and PyNaCl 1.6.2.
The harness uses the system user except for chown, the native writable tmp path,
default-source apt-get, a login-shell readiness marker and before/after nacl
version and path comparison. It preserves DOCKER_CONFIG before the rig changes
HOME. The owner also reran `bash scripts/termux_check.sh` successfully.
Real phone instructions use pkg. Physical phones, mobile data and Termux:API
remain untested.

## Boundaries and validation

New device platform module, two existing call sites, README, scripts/termux_check.sh and integration checks.

Device platform detection, default environment names, signed pairing and the loopback forward have regression coverage. Container results do not establish Android service behavior.
