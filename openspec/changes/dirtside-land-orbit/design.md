# Design

## Context and evidence

Core's `hermes_cli/plugins.py`, lines 649 to 674 at `84a0301`, registers text commands and refuses built-in collisions at lines 660 to 665. Latest 8d7061f has the same seam. The built-in registries on both cores contain neither name; the real dispatch tests verify this.

## Decision and rejected alternatives

Small bound adapters call the same long-form handler and only replace successful reply wording. Keep selection, picker, owner checks and storage in Commands. Reject duplicate targeting logic and core aliases.

Both handlers declare keyword-only source and forward it through select into Commands. Core's `hermes_cli/plugin_command_dispatch.py`, lines 11 to 32 at `84a0301`, passes source only to handlers declaring it. This preserves the review's native local authority without accepting relay wire labels. Native SessionSource dispatch covers named selection, the picker and orbit, while actual CLI/TUI sessions exercise selection and signed execution. Relay-decoded local sources retain long-form refusal and neither prompt path discloses device facts.

## Boundaries and validation

New shortcuts module, package wiring, README commands and real core dispatch tests.

Real dispatch tests cover selection, picker, usage, native source forwarding, signed execution and relay refusal.
