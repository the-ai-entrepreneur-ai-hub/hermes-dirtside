# Tasks

## Standalone device

- [x] Device modules import without core and state lookup preserves the legacy location order.
- [x] Standalone installation supports signed terminal commands and revoke.
- [x] The serving process does not load home or project dotenv credentials.
- [x] Console guidance and local pipx installation have regression coverage.

## State and isolation

- [x] Legacy service units retain both the Hermes profile and the device override.
- [x] Pytest and the shared rig discard outer state overrides without touching that state.
- [x] Relative overrides resolve absolutely for later processes in another directory.
- [x] Unknown tilde users produce the ordinary bounded CLI error.
