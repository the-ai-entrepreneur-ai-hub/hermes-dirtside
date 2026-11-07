# Tasks

## 1. Reproduce through core

- [x] 1.1 Extend the owned real-core rig to retain and close two fake devices; verify both devices can execute and teardown completes.
- [x] 1.2 Add target-switch conformance in both transports, with and without server in the middle; prove the unchanged implementation fails when A's directory is unavailable to B.
- [x] 1.3 Add deleted-cwd, transient-workdir and file-first controls; verify existing core failure rendering and local server behavior remain the reference.

## 2. Partition shell state

- [x] 2.1 Restore per-target durable cwd before core resolves a command while retaining each delegate's own snapshot; verify all new conformance cases pass.
- [x] 2.2 State the rule in A7, A16.5 and README, disclose the core cwd accessors, and verify documentation contracts.
- [x] 2.3 Raise only provider or environment budgets required by the delivered code; verify exact line counts, the size check and complexity at eight.

## 3. Integrate and report

- [x] 3.1 Run the full suite, lint, sizes, strict OpenSpec validation, doctor, clean-snapshot validation, loopback matrix, strict benchmark and unchanged 18-commit history check; retain exact outputs.
- [x] 3.2 Write the requested report with core and plugin line anchors, regression evidence, budget changes and limits; verify source hashes and unchanged core revision.

## 4. Correction 1: facade lifetime and offline bootstrap

- [x] 4.1 Reproduce same-target and changed-target reaping, offline-first export loss and unsafe cwd metadata through real core in both transports; retain red evidence without weakening existing cases.
- [x] 4.2 Move transition state to a bounded provider LRU, preserve surviving core cwd and server initialization, require contact before constructing device delegates and keep cwd metadata safe; verify the new cases and LRU boundary.
- [x] 4.3 Correct A16.5 terminal/file activation wording, document the parallel-completion ceiling and history cap, and state the minimum delivered provider budget with complexity eight and protocol one unchanged.
- [x] 4.4 Rerun all brief acceptance checks, verify exact final source/snapshot/core/history integrity and append the Correction 1 report with exact outputs and limits.

## 5. Correction 2: bootstrap isolation and optional metadata

- [x] 5.1 Reproduce the provider-lock stall, move bootstrap under the facade lock and verify another conversation's server execution and metadata finish while it waits.
- [x] 5.2 Reproduce offline optional temp-directory lookup and oversized-result failure, define a concrete forwarding method and audit core's other optional environment probes.
- [x] 5.3 Recover an existing delegate's live cwd after LRU history eviction and test both same-target and return selections.
- [x] 5.4 Update only README test counts, the Status date and the owner's live device-switch evidence, and state the exact provider budget.
- [x] 5.5 Run every acceptance check, finish pending Correction 1 tracking and append both correction report sections with exact outputs.
