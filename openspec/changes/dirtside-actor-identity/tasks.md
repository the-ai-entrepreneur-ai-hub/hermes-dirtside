# Tasks

Actor identity behavior recorded on 2026-11-10. The earlier three-core comparison found 38 context-constructor fixture failures and 39 unsupported older-core cases; those counts do not describe the current suite.

## 1. Shared sender authority

- [x] 1.1 Fixtures use the real common SessionContext constructor.
- [x] 1.2 The shared sender lookup distinguishes None from an empty actor and checks the module containing the two published API names.
- [x] 1.3 Real context binding, event absorption and copied tool contexts enforce sender authority through terminal/file dispatch and worker IPC.
- [x] 1.4 Registered selection, land, orbit, pairing, revocation, listing and picker commands keep foreign devices unavailable.
- [x] 1.5 Host policies, native source scope, direct ACP and cron retain their provenance rules.

## 2. Actor and route boundaries

- [x] 2.1 An empty actor beside a named route refuses before host or cron handling; empty-route controls keep their defined fallback.
- [x] 2.2 Real scoped follow-ups retain follower authority, opener steering and restoration.
- [x] 2.3 Actual conversation turns prove first device output, real event merging and second-call refusal without host execution, extra device work or a mid-turn hook.
- [x] 2.4 The plugin's eleven empty-route fallback surfaces are a strict subset of core's set, with normalization and source-only controls.
- [x] 2.5 Native local, webhook, API and relay-labelled bindings keep owner and same-sender controls beside chosen/default merge refusals.
- [x] 2.6 Status classifies no-sender refusal by its exception subtype without another identity lookup or message-text matching.
- [x] 2.7 Invalid or missing identity beside a named route refuses on every platform; explicit server and cron keep their rules.

## 3. Facts and isolation

- [x] 3.1 Hook facts update only at turn start; already frozen sections and history retain earlier facts.
- [x] 3.2 A known non-owner's captured device default can yield the fixed server fact; chosen devices still refuse.
- [x] 3.3 Inherited session and cron variables are removed before test collection, including in a child with planted launch values.
