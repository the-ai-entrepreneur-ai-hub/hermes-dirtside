# Design

## Context and evidence

Core's `website/docs/getting-started/termux.md`, lines 9 to 10 at `84a0301`, says its Termux package is broken. The base `dirtside/agent/executor.py` child_environment allowlist removes Termux system names. Termux's python-pynacl package build declares 1.6.2. Both cores accept the existing os string in the same version-1 hello.

## Decision and rejected alternatives

Use a new small platform module. Record names from the real image before choosing defaults; reject secret-shaped names. Preserve non-Termux defaults and explicit policy passthrough. Use only termux/termux-docker:aarch64 with seccomp unconfined first; do not fake Android services.

The owner-run scratch harness passed signed pairing, terminal commands, exit
codes, cancel and revoke on aarch64, Python 3.14.10 and PyNaCl 1.6.2. The copied
harness uses the system user except for chown, the native writable tmp path,
default-source apt-get, a login-shell readiness marker and before/after nacl
version and path comparison. It preserves DOCKER_CONFIG before the rig changes
HOME. The builder runs no Docker commands. The owner's final-tree rerun of
`bash scripts/termux_check.sh` passed; no harness or device-path code changed
in Correction 3. Real phone instructions keep pkg. Mobile data and
Termux:API remain untested.

## Boundaries and validation

New device platform module, two existing call sites, README, scripts/termux_check.sh and integration checks.

Tests run with isolated homes and ephemeral ports under nice. Each scenario below maps to the named test in tasks.md. First copy tests into a pristine archive of tree b67971b30ee06d71c69950e52f4bd135fc542afc and record red, then test the work tree and record green. No index changes, core edits, protocol changes or new private core imports. Shared docs and budgets may accumulate later package edits, recorded in the report.
