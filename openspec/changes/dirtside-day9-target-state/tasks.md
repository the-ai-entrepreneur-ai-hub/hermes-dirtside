# Tasks

## 1. Reproduce through core

- [x] 1.1 Extend the owned real-core rig to retain and close two fake devices; verify both devices can execute and teardown completes.
- [x] 1.2 Add target-switch conformance in both transports, with and without server in the middle; prove the unchanged implementation fails when A's directory is unavailable to B.
- [x] 1.3 Add deleted-cwd, transient-workdir and file-first controls; verify existing core failure rendering and local server behavior remain the reference.

## 2. Partition shell state

- [x] 2.1 Restore per-target durable cwd before core resolves a command while retaining each delegate's own snapshot; verify all new conformance cases pass.
- [x] 2.2 State the rule in A7, A16.5 and README, disclose the core cwd accessors, and verify documentation contracts.
- [x] 2.3 Raise only provider or environment budgets required by the delivered code; verify exact line counts, the size check and complexity at eight.

## 3. Facade lifetime and offline bootstrap

- [x] 3.1 Real-core regressions cover same-target and changed-target reaping, offline-first export loss and unsafe cwd metadata in both transports.
- [x] 3.2 A bounded provider LRU preserves transition state; device bootstrap requires contact and unavailable-device metadata stays safe.
- [x] 3.3 Terminal/file activation, the parallel-completion ceiling and history cap are documented with complexity eight and protocol one unchanged.

## 4. Bootstrap isolation and optional metadata

- [x] 4.1 Bootstrap holds the facade lock rather than the provider lock, so another conversation's server execution and metadata can finish.
- [x] 4.2 Optional temp-directory lookup and oversized-result recovery are safe while the device is unavailable.
- [x] 4.3 A live delegate's cwd survives LRU history eviction for same-target and return selections.
