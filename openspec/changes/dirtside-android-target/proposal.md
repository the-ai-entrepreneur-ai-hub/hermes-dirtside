# Proposal

## Why

A phone needs a Hermes-free device agent and its native Termux execution environment.

## What changes

Detect Termux, report Android (Termux), preserve a measured names-only system allowlist and document the real-phone check.

The owner's real aarch64 Termux userland in Docker passed signed pairing,
terminal shebang/Python/PREFIX commands, exit 7, cancel with exit 130 and revoke
on Python 3.14.10 and PyNaCl 1.6.2. The owner's final-tree rerun of
`bash scripts/termux_check.sh` also passed. No physical phone, mobile network
or Termux:API has been tested.

## Capabilities

### New capabilities

- `android-device`: A phone needs a Hermes-free device agent and its native Termux execution environment.

### Modified capabilities

None. Existing changes stay unarchived.

## Impact

New device platform module, two existing call sites, README, scripts/termux_check.sh and integration checks.
