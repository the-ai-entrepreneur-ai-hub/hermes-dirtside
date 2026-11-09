# Tasks

## 1. Regression tests

- [x] 1.1 Add tests/test_review_device_env.py for exact child names, login, stdin, passthrough, policy migration and CLI names-only output.

## 2. Red evidence

- [x] 2.1 Run the new tests on a pristine archive of 0ae9359 with only tests copied in; keep the red log.

## 3. Implementation

- [x] 3.1 Edit model.Policy, agent/config.py, agent/executor.py and cli.py; keep four-key files readable and serve's startup disclosure names-only.

## 4. Integration and disclosure

- [x] 4.1 Add tests/test_review_device_env_core.py using the real serve CLI and core terminal in both transports with fake .env keys.

## 5. Validation and checkpoint

- [x] 5.1 Run package tests and the fast suite, record green logs and any budget changes, then save WP1.diff and WP1-untracked.tgz.

## Correction 1

- [x] C1.1 Prove re-pair policy loss red, preserve validated names before pairing, and verify real HTTP re-pair without printing values.

## Correction 4

- [x] C4.1 Prove damaged old configuration rejects re-pairing on C3, recover only pairing with empty names and a constant note, and retain the real valid-name control.
