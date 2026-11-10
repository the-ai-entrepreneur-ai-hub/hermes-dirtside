# Design

## Context and evidence

Call register_device_routes(ctx) at registration. Feature-detect ctx.register_dashboard_token_route, call every fixed path with provider='dirtside' and its exact dirtside or dirtside-local scope, retain handles and dispose them on unload. If any call raises or returns None, dispose prior handles, mark the auth instance's route gate disabled and log one bounded line. Router handlers check that instance gate, so failed registration cannot leave executable routes even with dashboard auth off or an old route registration still present. No global per-home success flag.

Pinned core's `hermes_cli/plugins.py`, lines 736 to 776 at `84a0301` exposes auth-provider registration but no token-route method; 416-424 exposes unload. Core's `dashboard_auth/token_auth.py`, lines 31 to 40 at `84a0301` registers exact private paths without provider ownership; handlers already authenticate separately in dashboard/plugin_api.py:94-102 and dirtside/local.py:42-51. Latest 8d7061f moves ctx into plugins_context.py and still lacks this seam. Preserve released-core support via exactly one lazy private fallback function, explicitly commented as pending the token-route seam. Do not import the private module elsewhere.

The supplied core-pr-87462.diff defines register_dashboard_token_route(path, *, provider, required_scopes=()) -> PluginRegistration. Its withdrawal evidence in the brief names two upstream fixes still needed: resolve route/provider policy through the serving manager's scope, not ambient hermes_home_key, and reject any non-TokenPrincipal result. Dirtside cannot fix core's middleware without core edits; prepare an owner-voice seam request, do not claim the catalog is unblocked.

The instance starts disabled. Register the auth provider first and stop route acquisition if core refuses it. The dashboard BoundaryRoute checks the instance before FastAPI argument/body processing, and LocalAPI checks it independently before credentials. Dispose the gate before dropping handles; continue attempting other disposables if one fails. The released private API cannot remove its exact-path flags, so unload closes the instance gate even when an outer flag outlives it. A noncallable but present method is refusal, not absence.

Rejected: silently falling back after a present seam refuses registration widens auth; storing partial successes leaves half the routes live; trusting outer middleware alone fails cross-credential isolation and gate-off use.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_public_token_registration`: Provider-bound routes.
- `test_token_registration_refusal`: Atomic fail-closed registration.
- `test_legacy_token_registration`: Released-core fallback.
- `test_cross_credentials`: Independent credential checks.

## Correction 1

Pinned core's `hermes_cli/plugins.py`, lines 737 to 775 at `84a0301` upserts persistent auth providers; lines 1203 to 1240 unloads and re-registers on forced discovery. Core's `web_server_dashboard.py`, lines 1113 to 1114 at `84a0301` does not remount existing routers. Latest retains those contracts. A mounted router therefore resolves the public current provider at each request boundary, checks its gate before parsing, and binds that one instance across async/thread hops. Local handlers use the same request-bound instance, not the object whose methods were mounted. No registered provider, refused registration or disposed current gate means all routes stay closed.

Keep the live relay for a registry across re-registration through the existing persistent auth provider's runtime references, not a process-wide success flag. The registry, provider, workdir middleware and model/protocol/LocalAPI runtime types stay with the live relay because core evicts the plugin module namespace. Cached facades and in-flight requests retain that relay, its owner process, queues and streams; Access's validated context/owners refresh at registration. Auth instances and route gates remain separate. The owner-origin cache includes relay identity so a genuinely new registry/runtime cannot inherit an old owner claim. Different registries remain independent.

Rejected: re-enabling the stale instance gate leaves its old registry and local handlers bound; resolving the provider repeatedly within a request can mix credentials and runtime during reload; merely rebinding HTTP loses active work and cached in-process facades.

## Correction 2

The catalog-pin provider has none of C1's runtime reference fields, so registry-path equality is not a compatibility check. Require runtime_version 2 and the same registry path before reusing runtime references; version 1 starts a fresh Registry and Relay rather than retaining its old lookup API. Bind relay local ownership to the existing route gate: a closed gate routes through Client to the current serving owner or fails quickly if unavailable, never into abandoned local queues. Compatible ordinary rediscovery rebinds the gate and preserves in-flight handles. Mounted LocalAPI methods retain their original globals even after self rebinding, so canonicalize Outcome.state through the owning relay's RequestState and compare kill results by value. Core's legacy token path persists while its provider is absent and returns the generic unauthenticated/Unauthorized 401. That is not evidence of revocation: only exact 401 detail=device revoked stops the agent. Unknown-credential, generic and foreign errors retain existing retry/backoff.

Retired parked polls return without dispatching work. Local authentication refuses forwarding to the same incoming base URL when the new relay has not earned ownership, preventing a self-request loop while retaining secondary-server forwarding. Existing subprocess/thread tests that expected exit on generic 401 conflict with the new explicit-signal rule: their test transport deliberately loses revocation detail, requires two retries, then exercises owner-initiated shutdown with the original bounds. Explicit-revocation controls remain unchanged.

## Correction 4

The current provider can be disposed, or newly registered with routes not yet enabled, between /exec and /stream. LocalAPI refuses exactly HTTP 401 detail "Dirtside token routes are disabled" before submission or take_stream, so only this response is safe to retry. The Client uses one three-second monotonic deadline per /exec or /stream, closes rejections, preserves request id, rechecks the captured owner each attempt and never retries other statuses/details, transport failures, consumed streams or partial successful streams. Factor frame copying only to retain complexity 8. Do not widen route gates or replay ambiguous execution.

The real rediscovery test waits until the request is live and the owner's pending stream entry has actually been consumed, rather than treating RUNNING as attachment. Deterministic HTTP boundary tests cover both windows and the deadline; real signed loopback execution checks one history row and one device-side marker append. Final evidence adds 20 fresh serial client reload runs per core under six measured CPU workers, separate from the five correction-file rounds.

## Revoke exit

Both token recognition and the signed-route lookup filtered revoked rows, so an agent without an admitted poll received generic 401 forever. Keep the agent's exact-body rule unchanged. Signed transport and the token recognizer opt into retained paired credentials; ordinary registry lookups remain active-only. Represent a retained key as Revoked, not Device, including its persisted event time. Verify signature, 300-second freshness, nonce, sender and kind before exact 401 detail=device revoked on any signed device route. Invalid proof never receives the explicit stop answer or publishes ownership or liveness. Re-read a paired bearer after proof before touching the relay.

Same-owner re-pairing preserves its id and conversation choice. Archive the old paired public key and token hash separately with `COALESCE(revoked_at, ?)` before overwriting the row. Preserve the first revoke time, or use replacement time if still active. Pairing an already revoked name never reopens its old credential's window. Old proof cannot cancel or update the replacement; different-owner pairing still gets a fresh id. Pre-version replacements did not retain those credentials, so their old processes need manual shutdown.

Retained recognition requires `routes.enabled and revoked_at <= now < revoked_at + REVOKE_NOTICE_S`, with `REVOKE_NOTICE_S = 10`. This is the only rule under either registration API. Every qualifying signed request inside it receives the stop, including after a lost response or a parked poll has received one. Refusal, failure and unload remain closed.

Inside the window bad retained proof receives a different generic body from an unknown bearer. A gateway restart empties the process-local replay cache, so a captured message younger than 300 seconds can be replayed and receive the stop answer inside the persisted window.

An online device stops on its next qualifying signed request. Devices offline or backing off past the window receive core's generic rejection and keep retrying until someone stops them.

A retained principal authorizes nothing inside Dirtside. Released core token gates nevertheless accept it on other plugins' routes inside those ten seconds, as they already do for an active device bearer without its private key. Registering Dirtside's own paths cannot prove confinement on another plugin's routes. The day-8 retry test uses an unknown bearer through core's own gate; the shared masking helper remains only for separate proxy-fault controls.
