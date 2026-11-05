# Proposal

## Why

The Ubuntu gate fails the same five execution tests while macOS passes. Timeout ownership and shell-process assumptions must be portable before Dirtside can claim Linux support.

## What Changes

- Give the gateway the requested timeout, with a one-second device backstop grace that never exceeds the device policy cap. Use the same duration for execution and bounded chunk retries.
- Route explicit device timeouts through core's existing timeout rendering, preserving partial output, exit 124, the timeout flag and bounded-capture metadata. Keep ordinary exit 124, cancellation, loss and refusal distinct.
- Preserve timeout identity when the device also caps output.
- Keep bash alive in whole-group signal tests. Observe actual worker starts and acknowledged dispatch instead of depending on submission order or fixed sleeps.
- Audit every test for shell, temporary-directory, process-inspection and scheduling assumptions. Replace incidental host paths and readiness delays without weakening behavior or performance assertions.

## Capabilities

### New Capabilities

- `dirtside-timeout-ownership`: Gateway-owned timeout rendering with a policy-capped device backstop and bounded upload retries.

### Modified Capabilities

None. Main specs have not been synchronized; earlier changes remain active.

## Impact

The environment, domain timeout duration, executor, agent retry deadline, execution tests and test helpers change. Architecture records the revised timeout contract. No core edits, new core imports, dependencies, wire fields, manifest changes or skipped tests are needed.

Linux execution belongs to the owner. This change supplies source evidence, deterministic regression coverage, local acceptance outputs and a private handoff report. It does not commit, push, branch, archive, synchronize or access real user state.
