# Design

## Context and evidence

Core's `hermes_constants.py`, lines 194 to 201 at `84a0301`, resolves the active profile home. Both cores pin httpx[socks]==0.28.1 for Python >=3.14 in core's `pyproject.toml`, line 51 at `84a0301` and `8d7061f`. Before this change, gateway storage and home lookup were eager imports in `dirtside/__init__.py` and `dirtside/agent/config.py` at base tree b67971b. Latest 8d7061f has the same relevant contracts.

## Decision and rejected alternatives

Keep the legacy Hermes state path when importable, with DIRTSIDE_HOME first and ~/.dirtside only without Hermes. Reuse cli.handle and cli.setup_parser, omitting install-service in standalone mode. Do not install Hermes or read .env. Reject a second CLI implementation and a migration requiring re-pairing.

Legacy service rendering must preserve the selected Hermes profile separately from the device override. Inferring the profile from device_path().parents[1] loses that distinction when the override is set. Resolve that profile lazily through the same public core home helper, carry an absolute DIRTSIDE_HOME into the unit and keep logs beside device.json. Dry-run tests render both launchd and systemd without calling either manager.

Device lookup expands tilde and resolves DIRTSIDE_HOME to an absolute path just
as service_environment does. A relative value is anchored at the invocation's
working directory; use the same absolute override for a later process in another
directory, as generated service units do. Do not cache relative paths across
processes. An unknown tilde user raises RuntimeError at expansion; the shared
CLI handler reports the usual single-line error without exposing a traceback.

The new override must not escape test isolation. Clear an outer DIRTSIDE_HOME before pytest collection and when the shared rig builds its owned process environment. A real pairing test uses fake outer state and checks it stays byte-for-byte unchanged; matrix callers get the same protection without relying on pytest.

## Boundaries and validation

dirtside/__init__.py, agent/config.py, new agent/home.py and agent/console.py, cli.py, commands.py, pyproject.toml, plugin.yaml, README and size budgets.

Regression coverage imports the device without core, checks state lookup and service rendering, and runs signed terminal/revoke behavior through a standalone install.
