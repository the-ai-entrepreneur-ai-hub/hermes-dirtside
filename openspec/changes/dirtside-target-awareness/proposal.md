# Proposal

## Why

A mid-session target change must not leave the model using frozen device facts or guessing a remote tilde.

## What changes

Register a bounded public per-turn hook, disclose absolute home on selection and pin the existing file-path limit.

Plain-text reads and searches with absolute paths reach the device, subject to
core's gateway-side path-resolution limit. Write,
patch and extractable document reads use gateway-resolved paths and work only
when no component of the path is a symlink on the gateway;
on a macOS gateway that excludes /home, /tmp, /var and /etc. Terminal commands
are not affected, and a Termux home is not affected. This was tested on one
shared-disk rig. The fact line chooses its warning using gateway resolution,
and explicit server selection emits a fresh server line without changing
the frozen prompt.

If a non-empty configured string names another terminal backend, keep device
selection but append the configured-backend warning. Missing or empty settings
use stripped process TERMINAL_ENV or local, warning unless that result is
dirtside and explaining that terminal.backend is not set. Missing or unparseable
files follow the missing-setting rule; non-string values and a reader that
raises or exits remain silent. The hook and newly rendered frozen sections
return the shared warning without device facts after authorization. Already
frozen bytes are not rewritten; explicit server selection never warns. This
does not inspect or gate the frozen session's effective backend.

Every authorized turn's fact line remains in shared conversation history and
can disclose device facts to later participants whose device calls are denied.
Both device-selection replies also show the home to the whole chat.

## Capabilities

### New capabilities

- `per-turn-target-facts`: A mid-session target change must not leave the model using frozen device facts or guessing a remote tilde.

### Modified capabilities

None.

## Impact

New awareness module, registration, use reply, manifest, README, ARCHITECTURE and core-rig tests. No core changes.
