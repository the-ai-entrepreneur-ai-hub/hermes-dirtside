# Tasks

## 1. Sender-owned devices

- [x] 1.1 Commands, visibility, minting, provenance and old-registry migration have regression coverage.
- [x] 1.2 Access, the registry owner field and bounded local IPC sender identity protect every dispatch.
- [x] 1.3 Real-core group turns and defaults cover both transports.

## 2. Default trust and replacement

- [x] 2.1 Default squatting, cross-owner id reuse and privileged confirmations follow the same owner rules.
- [x] 2.2 Re-pairing preserves pending-name safety and documents the limited name-availability disclosure.
- [x] 2.3 Cross-owner completion cancels queued and running displaced work immediately without affecting same-owner reuse.

## 3. Native provenance

- [x] 3.1 Real CLI/TUI slash and turn paths accept native local authority and reject wrong-uid or messaging lookalikes.
- [x] 3.2 Policy-free local commands require scoped actual non-relay command provenance, including overlapping calls.
- [x] 3.3 Login authority and unsupported Windows host subjects match core's principal mapping.
