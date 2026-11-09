# Device child environments

## Why

Keep the device agent's credentials out of child commands without changing the signed protocol.

Review point, verbatim (2026-11-08):

2. [executor.py](https://github.com/the-ai-entrepreneur-ai-hub/hermes-dirtside/blob/0ae9359b4bd29114072343983abd0b624269acc3/dirtside/agent/executor.py#L93-L96) runs model-written scripts with no `env=`, so they inherit the device agent's whole environment. `hermes dirtside serve` loads the device's Hermes `.env`, so every provider key there is visible to model commands. Hermes' local backend strips those keys. Pass an explicit minimal env: PATH, HOME, USER, LANG/LC_*, TERM and TMPDIR, plus a passthrough list the user declares in the device policy.

## What changes

- Add tests/test_review_device_env.py for exact child names, login, stdin, passthrough, policy migration and CLI names-only output.
- Run the new tests on a pristine archive of 0ae9359 with only tests copied in; keep the red log.
- Edit model.Policy, agent/config.py, agent/executor.py and cli.py; keep four-key files readable and serve's startup disclosure names-only.
- Add tests/test_review_device_env_core.py using the real serve CLI and core terminal in both transports with fake .env keys.
- Run package tests and the fast suite, record green logs and any budget changes, then save WP1.diff and WP1-untracked.tgz.

## Capabilities

### New capabilities
- `dirtside-review-device-env`: The requirements and executable scenarios in this change.

### Modified capabilities
None.

## Impact

Only this plugin work tree, tests, documentation and private review notes. Keep signed device protocol version 1, requires_hermes >=0.22.7, and existing dependencies. No core edits, archive, commit or network writes.
