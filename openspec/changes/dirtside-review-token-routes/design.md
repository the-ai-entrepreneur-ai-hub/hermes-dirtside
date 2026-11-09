# Design

## Context and evidence

Call register_device_routes(ctx) at registration. Feature-detect ctx.register_dashboard_token_route, call every fixed path with provider='dirtside' and its exact dirtside or dirtside-local scope, retain handles and dispose them on unload. If any call raises or returns None, dispose prior handles, mark the auth instance's route gate disabled and log one bounded line. Router handlers check that instance gate, so failed registration cannot leave executable routes even with dashboard auth off or an old route registration still present. No global per-home success flag.

Core 84a0301 hermes_cli/plugins.py:736-776 exposes auth-provider registration but no token-route method; 416-424 exposes unload. dashboard_auth/token_auth.py:31-40 registers exact private paths without provider ownership; handlers already authenticate separately in dashboard/plugin_api.py:94-102 and dirtside/local.py:42-51. Latest 8d7061f moves ctx into plugins_context.py and still lacks this seam. Preserve released-core support via exactly one lazy private fallback function, explicitly commented as pending the token-route seam. Do not import the private module elsewhere.

The supplied core-pr-87462.diff defines register_dashboard_token_route(path, *, provider, required_scopes=()) -> PluginRegistration. Its withdrawal evidence in the brief names two upstream fixes still needed: resolve route/provider policy through the serving manager's scope, not ambient hermes_home_key, and reject any non-TokenPrincipal result. Dirtside cannot fix core's middleware without core edits; prepare an owner-voice seam request, do not claim the catalog is unblocked.

Rejected: silently falling back after a present seam refuses registration widens auth; storing partial successes leaves half the routes live; trusting outer middleware alone fails cross-credential isolation and gate-off use.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_public_token_registration`: Provider-bound routes.
- `test_token_registration_refusal`: Atomic fail-closed registration.
- `test_legacy_token_registration`: Released-core fallback.
- `test_cross_credentials`: Independent credential checks.
