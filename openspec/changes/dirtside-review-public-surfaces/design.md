# Design

## Context and evidence

Use the owner-supplied validator-findings-0ae9359.txt as the verified baseline: 29 findings, six runtime sites and 23 dev-tool sites. Move all non-runtime internal-import modules under tests, where they accurately belong; update all callers, README commands, scripts, CI and size budgets instead of adding re-export shims or test_ filenames outside tests. Keep check_sizes.py and other internal-free tools where useful.

At core 84a0301 hermes_cli/plugin_validate_private_imports.py:27-68 defines public imports; tools.environments.base:BaseEnvironment and gateway.session_context:get_session_env are public, EnvironmentConnectionError, LocalEnvironment and token_auth are not. plugin_validate_core_override.py:26,40 skips tests directories and test_ files. Latest 8d7061f reads hermes_cli/data/plugin_api.json through _public_api instead; the three transitional targets remain private. A new test invokes private_import_findings on a clean export, not the dirty checkout or a weakened copy of the validator, and asserts the exact three sites once each.

README and architecture explain the minimal environment, device-only passthrough, sender ownership, public middleware and three transitional imports. The notes-only seam request names #87462's two rejected assumptions and the local-backend handoff/error-documentation contract. No network posting is authorized. Validation exports include intended untracked files before the owner commits; the historical git log stays at 20 commits.

Rejected: teaching the validator to ignore tools hides debt; a source-pattern substitute is not the catalog check; renaming non-tests test_ is misleading; claiming released cores implement the seam is false.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_private_imports_are_exact_transitional_set`: Exact transitional surface.
- `test_development_entrypoints`: Honest development layout.
- `test_review_documentation`: Documented limits.
