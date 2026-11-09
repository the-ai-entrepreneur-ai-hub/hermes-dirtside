# Design

## Context and evidence

Use one environment builder at the executor spawn, not a denylist or a gateway-supplied list. Copy only set PATH, HOME, USER, LANG, LC_*, TERM, TMPDIR and policy env_passthrough names. The agent keeps its environment. Login startup files remain owner-controlled code, not a sandbox. parse_policy accepts the old four required keys plus the optional list, validates names, count and uniqueness, and serializes the new field. A device-only policy command shows names, sets a replacement list or clears it; serve prints names and loads changes only at restart.

At pinned core, core's `hermes_cli/env_loader.py`, lines 420 to 431 at `84a0301` and 639 load .env into the CLI process; core's `tools/environments/local.py`, lines 381 to 401 at `84a0301` builds the local child's scrubbed environment and 1133-1160 passes it to Popen. Dirtside's missing env= is the boundary to fix, not core's loader. The supplied validator-findings-0ae9359.txt is the baseline import evidence. Latest 8d7061f preserves these execution contracts. No dependency, wire field or protocol-version change.

Rejected: deleting variables from os.environ would damage the agent; a provider-key blacklist misses unknown credentials; a gateway option would let the gateway widen device policy.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_executor_exact_environment`: Minimal child environment.
- `test_login_environment`: Login isolation.
- `test_declared_passthrough`: Owner passthrough.
- `test_policy_files`: Policy compatibility.
- `test_policy_cli`: Device policy CLI.
- `test_serve_dotenv_isolation`: Real serve isolation.

## Correction 1

Re-pairing reads and validates the existing device file before contacting the gateway and preserves its env_passthrough names, never values. Other policy fields retain the existing default-reset behavior. A fresh pairing still starts with no passthrough. test_repair_preserves_passthrough_names exercises the real CLI handler and signed HTTP pairing twice.

## Correction 4

The earlier validated-file requirement applies when that file can be read safely and validated. Pairing must still recover credentials when it cannot: catch only configuration read/validation failures before the network operation, print a constant names-only warning and retain an empty tuple. Keep DeviceConfig.load strict for serve/status/policy and preserve atomic private save. Do not catch gateway or credential failures as old-config recovery. Real signed pairing tests cover permission denial, widened mode, malformed JSON and the reviewer's private empty object, alongside valid-name continuity.
