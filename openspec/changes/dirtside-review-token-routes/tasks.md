# Tasks

## 1. Registration and closure

- [x] 1.1 Fixed device and local paths use the public context method with exact scopes and retained disposable handles.
- [x] 1.2 Refusal, failure, missing or noncallable registration closes every handler and disposes partial handles.
- [x] 1.3 Dashboard sessions do not bypass closure; disabled or inactive registrations recognize no Dirtside credentials on any token route.

## 2. Live runtime continuity

- [x] 2.1 Mounted requests and local handlers bind to the current provider while compatible rediscovery preserves live relay state.
- [x] 2.2 Disable/re-enable, registry replacement, in-flight work and both transports retain their defined behavior.
- [x] 2.3 Only same-path runtime version 2 is reused; older providers start fresh, retired relays use the current Client, and unclaimed self-forwarding refuses.
- [x] 2.4 Mounted-generation close and kill compare terminal states by value.
- [x] 2.5 Generic and unknown-credential poll/upload failures retry; only the exact explicit-revoked signal stops an agent.

## 3. Worker replay

- [x] 3.1 Real-loader worker calls inside registrations 1, 5 and 9 retain one execution and complete output.
- [x] 3.2 Execution and stream 401s retry before handler work within the same fixed deadline and request identity.
- [x] 3.3 Other statuses and transport failures do not replay work; a permanently closed recorded owner remains bounded.

## 4. Revoke exit

- [x] 4.1 Signed routes, invalid proof, replays, offline subprocesses, real uploads and re-pairing have regression coverage.
- [x] 4.2 Retained proof is separate from active authority; rotated paired credentials retain the first event time and same-owner choices remain stable.
- [x] 4.3 The ten-second window uses whole gateway seconds; a clock change can reopen or close it, and late devices need manual shutdown.
- [x] 4.4 The 2026-11-10 released-core checks measured foreign-route exposure and the original ten-second bound. Current provider-bound tests assert refusal with working controls.
- [x] 4.5 Independent device clocks, repeated answers, restart, replacement and invalid-proof controls preserve the original window.
- [x] 4.6 Restart empties the replay cache; credentials replaced before retained storage existed need manual shutdown.
