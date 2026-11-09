# Proposal

## Why

The existing target choice needs short commands without another authorization path.

## What changes

Register land and orbit through the public command registry and delegate to Commands.
Forward native command source to preserve host authority and relay refusal without
a second authorization path.

## Capabilities

### New capabilities

- `target-shortcuts`: The existing target choice needs short commands without another authorization path.

### Modified capabilities

None. Existing changes stay unarchived.

## Impact

New shortcuts module, package wiring, README commands and real core dispatch tests.
