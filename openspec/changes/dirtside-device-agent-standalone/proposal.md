# Proposal

## Why

Devices should not need a full gateway installation or load its secrets just to execute signed work.

## What changes

Lazy gateway imports, compatible device state discovery, bounded HTTPX dependency and a shared dirtside-agent console entry point.

## Capabilities

### New capabilities

- `standalone-device`: Devices should not need a full gateway installation or load its secrets just to execute signed work.

### Modified capabilities

None. Existing changes stay unarchived.

## Impact

dirtside/__init__.py, agent/config.py, new agent/home.py and agent/console.py, cli.py, commands.py, pyproject.toml, plugin.yaml, README and size budgets.
