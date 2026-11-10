# Design

## Context and evidence

Call register_device_routes(ctx) at registration. Feature-detect ctx.register_dashboard_token_route, call every fixed path with provider='dirtside' and its exact dirtside or dirtside-local scope, retain handles and dispose them on unload. If any call raises or returns None, dispose prior handles, mark the auth instance's route gate disabled and log one bounded line. Router handlers check that instance gate, so failed registration cannot leave executable routes even with dashboard auth off or an old route registration still present. No global per-home success flag.

The method core is Hermes 0.23.1 (`3b421578588243f920886e6fe79a6faa87ea026e`) with the single public commit of core PR #151760 (`7dce8c38e8c998c52c4c139df340a0bffecc77e6`) applied. Its context registers exact paths only under the plugin's discovered dashboard mount, using this plugin's active auth-provider handle and launch scope (core's `hermes_cli/plugins_context.py`, `PluginContext.register_dashboard_token_route`, lines 585 to 640 at that public PR commit). There is no private registration fallback.

Core's bound gate calls only the current owning provider and requires a matching TokenPrincipal provider, launch home and scopes (core's `hermes_cli/dashboard_auth/token_auth.py`, `_authenticate_bound_token`, lines 116 to 159 at public PR commit `7dce8c38e8c998c52c4c139df340a0bffecc77e6`). In that file, `authenticate_token`, lines 86 to 113, skips providers with any current bound policy on legacy unbound routes. Removing the last policy while the provider remains registered removes that exclusion; it is not a permanent provider classification.

The instance starts disabled. Register the auth provider first and stop route acquisition if core refuses it. The dashboard BoundaryRoute checks the instance before FastAPI argument/body processing, and LocalAPI checks it independently before credentials. Close the gate before dropping handles and attempt every remaining disposal if one raises. Missing, noncallable, refused and raising registration all stay closed with a bounded cause warning.

Rejected: silently falling back after a present seam refuses registration widens auth; storing partial successes leaves half the routes live; trusting outer middleware alone fails cross-credential isolation and gate-off use.

## Validation and migration

Historical regression evidence used pristine 0ae9359 and the earlier prepared cores. Current tests use the real method context, manager, discovered mount and bound middleware, with isolated homes. The seam-only change owns current full-suite, matrix and repeated-file verification.

- `test_public_token_registration`: Provider-bound routes.
- `test_token_registration_refusal`: Atomic fail-closed registration.
- `test_unavailable_method_closes_every_route`: Missing or noncallable public method, with real-method success controls.
- `test_cross_credentials`: Independent credential checks.

## Correction 1

Pinned core's `hermes_cli/plugins.py`, lines 737 to 775 at `84a0301` upserts persistent auth providers; lines 1203 to 1240 unloads and re-registers on forced discovery. Core's `web_server_dashboard.py`, lines 1113 to 1114 at `84a0301` does not remount existing routers. Latest retains those contracts. A mounted router therefore resolves the public current provider at each request boundary, checks its gate before parsing, and binds that one instance across async/thread hops. Local handlers use the same request-bound instance, not the object whose methods were mounted. No registered provider, refused registration or disposed current gate means all routes stay closed.

Keep the live relay for a registry across re-registration through the existing persistent auth provider's runtime references, not a process-wide success flag. The registry, provider, workdir middleware and model/protocol/LocalAPI runtime types stay with the live relay because core evicts the plugin module namespace. Cached facades and in-flight requests retain that relay, its owner process, queues and streams; Access's validated context/owners refresh at registration. Auth instances and route gates remain separate. The owner-origin cache includes relay identity so a genuinely new registry/runtime cannot inherit an old owner claim. Different registries remain independent.

Rejected: re-enabling the stale instance gate leaves its old registry and local handlers bound; resolving the provider repeatedly within a request can mix credentials and runtime during reload; merely rebinding HTTP loses active work and cached in-process facades.

## Correction 2

The catalog-pin provider has none of C1's runtime reference fields, so registry-path equality is not a compatibility check. Require runtime_version 2 and the same registry path before reusing runtime references; version 1 starts a fresh Registry and Relay. A closed relay gate uses Client to the current serving owner rather than abandoned queues. Compatible rediscovery keeps in-flight handles; terminal states are canonicalized by value across module generations. Targeted unload removes public policies, so an unregistered path reaches ordinary downstream session auth. This generic rejection is not revocation: only exact 401 detail=device revoked stops the agent.

Retired parked polls return without dispatching work. Local authentication refuses forwarding to the same incoming base URL when the new relay has not earned ownership, preventing a self-request loop while retaining secondary-server forwarding. Existing subprocess/thread tests that expected exit on generic 401 conflict with the new explicit-signal rule: their test transport deliberately loses revocation detail, requires two retries, then exercises owner-initiated shutdown with the original bounds. Explicit-revocation controls remain unchanged.

## Correction 4

The current provider can be disposed, or newly registered with routes not yet enabled, between /exec and /stream. LocalAPI refuses exactly HTTP 401 detail "Dirtside token routes are disabled" before submission or take_stream, so only this response is safe to retry. The Client uses one three-second monotonic deadline per /exec or /stream, closes rejections, preserves request id, rechecks the captured owner each attempt and never retries other statuses/details, transport failures, consumed streams or partial successful streams. Factor frame copying only to retain complexity 8. Do not widen route gates or replay ambiguous execution.

The real rediscovery test waits until the request is live and the owner's pending stream entry has actually been consumed, rather than treating RUNNING as attachment. Deterministic HTTP boundary tests cover both windows and the deadline; real signed loopback execution checks one history row and one device-side marker append. Final evidence adds 20 fresh serial client reload runs per core under six measured CPU workers, separate from the five correction-file rounds.

## Revoke exit

Both token recognition and the signed-route lookup filtered revoked rows, so an agent without an admitted poll received generic 401 forever. Keep the agent's exact-body rule unchanged. Signed transport and the token recognizer opt into retained paired credentials; ordinary registry lookups remain active-only. Represent a retained key as Revoked, not Device, including its persisted event time. Verify signature, 300-second freshness, nonce, sender and kind before exact 401 detail=device revoked on any signed device route. Invalid proof never receives the explicit stop answer or publishes ownership or liveness. Re-read a paired bearer after proof before touching the relay.

Same-owner re-pairing preserves its id and conversation choice. Archive the old paired public key and token hash separately with `COALESCE(revoked_at, ?)` before overwriting the row. Preserve the first revoke time, or use replacement time if still active. Pairing an already revoked name never starts a new window for its old credential. Old proof cannot cancel or update the replacement; different-owner pairing still gets a fresh id. Pre-version replacements did not retain those credentials, so their old processes need manual shutdown.

Retained recognition requires `routes.enabled and revoked_at <= now < revoked_at + REVOKE_NOTICE_S`, with `REVOKE_NOTICE_S = 10`. The window runs from the credential's first revoke or replacement. It follows the gateway's clock in whole seconds, so it lasts 9 to 10 seconds. Setting that clock back into the window reopens it, and setting it forward closes it early. This is the only rule through the public method. Every qualifying signed request inside it receives the stop, including after a lost response or a parked poll has received one. Refusal, failure and unload remain closed.

Inside the window bad retained proof receives a different generic body from an unknown bearer. A gateway restart empties the process-local replay cache, so a captured message younger than 300 seconds can be replayed and receive the stop answer inside the persisted window.

An online device stops on its next qualifying signed request. Devices offline or backing off past the window receive core's generic rejection and keep retrying until someone stops them.

A retained principal authorizes nothing inside Dirtside and cannot authorize foreign bound routes. Legacy unbound routes skip Dirtside while it has a bound policy. A longer revoke window is possible on the bound gate and is outside this change. The day-8 retry test uses an unknown bearer through core's own gate; separate proxy-fault controls retain their masking helper.
