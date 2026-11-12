# Tasks

## 1. Plugin-owned state

- [x] 1.1 Regression coverage includes terminal-import exclusion, task/session mismatch, idle switches, repeated target changes and core-local credential control.
- [x] 1.2 Public middleware and the manifest describe the same explicit-workdir callback.
- [x] 1.3 Plugin history, per-target facades and the isolated local factory replace private cwd access.

## 2. Lifetime and defaults

- [x] 2.1 Context-free cleanup removes only plugin-owned snapshot paths, with the serving owner still checked.
- [x] 2.2 Registry-backed conversation defaults survive reload and idle recreation while explicit overrides remain live and cron keeps its rule.
- [x] 2.3 Desktop uses the shared resolver under local identity and retains missing/revoked 404.
- [x] 2.4 Device-routing guidance distinguishes terminal execution from gateway-side file-path resolution.
