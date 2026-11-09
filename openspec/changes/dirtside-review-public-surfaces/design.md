# Design

## Context and evidence

Use the owner-supplied validator-findings-0ae9359.txt as the verified baseline: 29 findings, six runtime sites and 23 dev-tool sites. Move all non-runtime internal-import modules under tests, where they accurately belong; update all callers, README commands, scripts, CI and size budgets instead of adding re-export shims or test_ filenames outside tests. Keep check_sizes.py and other internal-free tools where useful.

Pinned core's `hermes_cli/plugin_validate_private_imports.py`, lines 27 to 68 at `84a0301` defines public imports; tools.environments.base:BaseEnvironment and gateway.session_context:get_session_env are public, EnvironmentConnectionError, LocalEnvironment and token_auth are not. Core's `plugin_validate_core_override.py`, lines 26, 40 at `84a0301` skips tests directories and test_ files. Latest 8d7061f reads hermes_cli/data/plugin_api.json through _public_api instead; the three transitional targets remain private. A new test invokes private_import_findings on a clean export, not the dirty checkout or a weakened copy of the validator, and asserts the exact three sites once each.

README and architecture explain the minimal environment, device-only passthrough, sender ownership, public middleware and three transitional imports. The notes-only seam request names #87462's two rejected assumptions and the local-backend handoff/error-documentation contract. No network posting is authorized. Validation exports include intended untracked files before the owner commits; the historical git log stays at 20 commits.

Rejected: teaching the validator to ignore tools hides debt; a source-pattern substitute is not the catalog check; renaming non-tests test_ is misleading; claiming released cores implement the seam is false.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_private_imports_are_exact_transitional_set`: Exact transitional surface.
- `test_development_entrypoints`: Honest development layout.
- `test_review_documentation`: Documented limits.

Final adapter tracing also corrects an earlier WP2 boundary, not a new capability: core's actual email extractor preserves quoted local parts with ASCII spaces. The native-identity regression first fails the intermediate predicate, then passes on both cores after preserving bounded printable ids. The same WP2 file now populates queued and finished request history before old-schema migration. Its spec/design own those runtime and data-preservation contracts; WP5 reports the cumulative correction and maps all new test functions to named scenarios.

## Correction 1

Pinned core's `agent/system_prompt.py`, lines 113 to 135 at `84a0301`, freezes plugin sections at first render and lines 138 to 167 restore persisted bytes. Keep that core contract and document precisely that all participants can receive the first render's device name, OS, home and online state, including stale or unauthorized facts, through the shared model context. Per-turn dispatch still checks the sender. test_frozen_group_prompt_disclosure_matches_core exercises the real frozen accessor and denies the later sender's execution.

Server-target commands execute as the gateway user, can read local.secret and can authenticate local IPC as local. This is not an ownership boundary against a sender with arbitrary server execution; core approvals and messaging allowlists decide that trust. test_server_execution_limit_is_explicit demonstrates it only in temporary homes and checks the threat-table disclosure.

Official WSL documentation https://wsl.dev/technical-documentation/interop/ says WSL_INTEROP selects the interop server; without it /init tries /run/WSL sockets up the parent chain. Do not claim it is always required. Recommend passing its existing value for Windows .exe tools when fallback cannot reach a live server; enabled interop and an executable path are still required. No new WSL-host execution is claimed.

## Correction 2

Keep the exact three transitional imports and all previous trust limitations. Document that configured defaults are snapshotted while explicit target changes remain live; configuration reload cannot rewrite an already frozen pre-upgrade prompt. Describe compatible runtime reuse, retired Client routing, immediate displaced-owner gateway cancellation, and the agent's exact explicit-revocation stop rule versus retry of ambiguous 401. Report unchanged original and C1 gates as history, not as new C2 verification. Enumerate every path changed since both C1 and WP5, exact budget deltas, all failed runs and cleanup of owned test processes.

Generic-auth retry supersedes the older assumption that every revoked agent exits automatically: keep revoked-token recognition invalid and disclose owner stop/re-pair when no explicit signal arrives. Preserve explicit-signal automatic shutdown, immediate gateway cancellation, secondary-server forwarding and all existing numeric gates. Include test_cli.py, test_agent.py and network_support.py in the five-pass file union after updating those conflicting expectations.

## Correction 3

Use the prepared cores only, not the owner's live ca43606 install. Reproduce same-uid local slash identity through native authenticated sessions and prove the full device flow. Fix only the owner-loss test's pid-file/teardown handling, with a retained-cwd regression; do not alter agent.loop. Preserve all numeric bounds, day-9 files, existing default snapshots and three private-import sites. The optional omission of server rows is not a few-line compatible optimization: an absent row cannot distinguish an earlier server conversation from a new conversation after the default changes. Report this omission explicitly.

All final checks run in fresh temporary homes and serially, including five rounds of the whole C1-C3 changed test/helper union. Inventory every changed path since C2 and WP5, record all attempts and exact outputs, verify no owned processes remain, reconstruct cumulative C3 checkpoints and remove temporary helpers. Manual review is not described as independent-agent review.

## Correction 4

Core file-and-line references must say core's filename and lines at the prepared revision, never look like repository-local citations. Search all markdown, including historical OpenSpec designs; preserve local citations and verbatim review links. Run the owner's unchanged authorized doc-cite.js, not a replacement or waiver.

Correct all dashboard/Webapp/forwarded-login authority and unsupported Windows sid: disclosure, use --code=<code> because codes may start with a hyphen, and scope chosen-machine claims to terminal commands. Re-pair recovery is names-only and the device path limit is supplied owner evidence, not a new live run. Keep exactly three private import sites, all earlier limits and original day-9 assertions.

Run behavioral red against exact C3 plus final regression tests on both cores; separate already-passing controls and implementation failures. Rerun pinned fast, both full suites, Ruff, exact exhausted budgets, strict OpenSpec, both doctors and native clean-export validators, matrix 8/8 and strict benchmark. Repeat the entire C1-C4 changed test/helper union five times, plus 20 fresh serial client reload cases on each core under six measured CPU workers. Save/reconstruct C4 checkpoints, inventory since C3 and WP5, audit invariants and owned processes, remove helpers and append full outputs without rewriting earlier report history.
